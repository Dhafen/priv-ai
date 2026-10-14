"""Inspect the actual compiled app; never infer packaging from source alone."""
import argparse
from pathlib import Path
import plistlib
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--signed', metavar='TEAM_ID')
    args = parser.parse_args()
    app = args.app
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'com.dhafen.privai', 'Wrong Bundle ID'
    assert info['CFBundleDisplayName'] == 'Priv AI', 'Wrong display name'
    forbidden = [p for p in app.rglob('*') if p.is_file() and (
        p.suffix in {'.gguf', '.safetensors', '.p8', '.p12', '.key', '.pem'}
        or p.name.startswith('layer_') and p.suffix == '.bin')]
    assert not forbidden, 'Weights or signing secrets were bundled into the app'
    kernels = list(app.rglob('Kernels.metal.txt'))
    assert kernels, 'Swiftlet Metal kernel resource missing'
    executable = app / info['CFBundleExecutable']
    symbols = subprocess.check_output(['strings', str(executable)], text=True)
    for marker in ('Qwen3.6-35B-A3B-qpack', 'SwiftletEngine', 'QPACK'):
        assert marker in symbols, f'Compiled Swiftlet/model marker missing: {marker}'
    if args.signed:
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        entitlements = plistlib.loads(subprocess.check_output([
            'codesign', '-d', '--entitlements', ':-', str(app)], stderr=subprocess.DEVNULL))
        assert entitlements['com.apple.developer.team-identifier'] == args.signed
        assert entitlements['application-identifier'].endswith('.com.dhafen.privai')
        assert entitlements.get('com.apple.developer.healthkit') is True
        assert entitlements.get('com.apple.developer.kernel.increased-memory-limit') is True
        assert not entitlements.get('get-task-allow', False)
    print('Verified actual app: own Bundle ID, Swiftlet kernels/code, Qwen download source, no bundled weights/secrets.')
    print('Physical iPhone model download and inference: UNVERIFIED.')


if __name__ == '__main__':
    main()
