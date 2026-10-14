#!/bin/bash
set -euo pipefail
umask 077
SIGNING_DIR="$RUNNER_TEMP/privai-signing"
mkdir -p "$SIGNING_DIR"
export SIGNING_DIR
python3 - <<'PY'
import base64, os
from pathlib import Path
root = Path(os.environ['SIGNING_DIR'])
for secret, filename in [('ASC_PRIVATE_KEY_B64', 'AuthKey.p8'),
                         ('IOS_DISTRIBUTION_P12_B64', 'distribution.p12'),
                         ('IOS_PROVISIONING_PROFILE_B64', 'distribution.mobileprovision')]:
    (root / filename).write_bytes(base64.b64decode(os.environ[secret], validate=True))
PY
security cms -D -i "$SIGNING_DIR/distribution.mobileprovision" > "$SIGNING_DIR/profile.plist"
python3 - <<'PY'
import datetime, os, plistlib
from pathlib import Path
root = Path(os.environ['SIGNING_DIR'])
profile = plistlib.loads((root / 'profile.plist').read_bytes())
team = os.environ['APPLE_TEAM_ID']
entitlements = profile['Entitlements']
assert team in profile['TeamIdentifier'], 'Signing profile belongs to a different team'
assert entitlements['application-identifier'].endswith('.com.dhafen.privai'), 'Wrong Bundle ID'
assert not entitlements.get('get-task-allow', False), 'Distribution profile required'
assert entitlements.get('com.apple.developer.healthkit'), 'Profile must support HealthKit'
assert entitlements.get('com.apple.developer.kernel.increased-memory-limit'), 'Profile must support Increased Memory Limit'
assert profile['ExpirationDate'] > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), 'Profile expired'
profile_path = Path.home() / 'Library/MobileDevice/Provisioning Profiles' / (profile['UUID'] + '.mobileprovision')
profile_path.parent.mkdir(parents=True, exist_ok=True)
profile_path.write_bytes((root / 'distribution.mobileprovision').read_bytes())
with open(os.environ['GITHUB_ENV'], 'a') as env:
    env.write('PROFILE_UUID=' + profile['UUID'] + '\n')
    env.write('ASC_KEY_PATH=' + str(root / 'AuthKey.p8') + '\n')
PY
KEYCHAIN_PATH="$RUNNER_TEMP/privai-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$SIGNING_DIR/distribution.p12" -P "$IOS_DISTRIBUTION_P12_PASSWORD" -T /usr/bin/codesign -t cert -f pkcs12 -k "$KEYCHAIN_PATH" >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null
security list-keychains -d user -s "$KEYCHAIN_PATH" "$HOME/Library/Keychains/login.keychain-db"

