"""One-time Windows setup of signing secrets; private values never go to stdout.

Requires cryptography and asn1crypto. The Apple API key is read from a local
file. Cached certificate/private-key material is protected by Windows DPAPI.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, utils
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'com.dhafen.privai'
CACHE = ROOT / 'work/signing/distribution.dpapi'


def b64(data):
    return base64.b64encode(data).decode('ascii')


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Run signing setup on Windows; the local cache uses Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypto = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypto.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypto.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = function(ctypes.byref(incoming), 'Priv AI signing cache', None, None, None, 1, ctypes.byref(outgoing))
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


class AppleAPI:
    def __init__(self, key_file, key_id, issuer):
        self.key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        self.key_id, self.issuer = key_id, issuer

    def token(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
        now = int(time.time())
        message = encode({'alg': 'ES256', 'kid': self.key_id, 'typ': 'JWT'}) + b'.' + encode({
            'iss': self.issuer, 'iat': now - 10, 'exp': now + 600, 'aud': 'appstoreconnect-v1'})
        r, s = utils.decode_dss_signature(self.key.sign(message, ec.ECDSA(hashes.SHA256())))
        signature = base64.urlsafe_b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).rstrip(b'=')
        return (message + b'.' + signature).decode()

    def request(self, route, method='GET', body=None, query=None):
        url = 'https://api.appstoreconnect.apple.com/v1/' + route
        if query:
            url += '?' + urlencode(query)
        request = Request(url, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Authorization': 'Bearer ' + self.token(), 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=60) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except HTTPError as error:
            # Report Apple error codes, never request headers or response bodies.
            try:
                codes = ', '.join(item['code'] for item in json.load(error).get('errors', []))
            except Exception:
                codes = 'unknown error'
            raise RuntimeError(f'Apple API HTTP {error.code}: {codes} ({route})') from None


def github(args, *command, value=None):
    result = subprocess.run(['gh', *command, '--repo', args.repository],
                            input=value, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub operation failed: ' + ' '.join(command[:3]))
    return result.stdout


def signing(args, api, bundle):
    from asn1crypto import cms
    if CACHE.exists():
        state = json.loads(protect(CACHE.read_bytes(), decrypt=True))
        api.request('certificates/' + state['certificate_id'])
    else:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, 'Priv AI TestFlight')
        ])).sign(private, hashes.SHA256())
        certificate = api.request('certificates', 'POST', {'data': {
            'type': 'certificates', 'attributes': {'certificateType': 'DISTRIBUTION',
                'csrContent': csr.public_bytes(serialization.Encoding.PEM).decode()}}})['data']
        cert = x509.load_der_x509_certificate(base64.b64decode(certificate['attributes']['certificateContent']))
        password = secrets.token_urlsafe(40)
        p12 = pkcs12.serialize_key_and_certificates(b'Priv AI Distribution', private, cert, None,
                    serialization.BestAvailableEncryption(password.encode()))
        state = {'certificate_id': certificate['id'], 'p12': b64(p12), 'password': password}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(protect(json.dumps(state).encode()))

    profile_name = 'Priv AI Internal ' + state['certificate_id']
    candidates = api.request('profiles', query={'filter[name]': profile_name, 'limit': 100})['data']
    valid = [item for item in candidates if item['attributes']['profileState'] == 'ACTIVE']
    if valid:
        profile = api.request('profiles/' + valid[0]['id'])['data']
    else:
        profile = api.request('profiles', 'POST', {'data': {
            'type': 'profiles', 'attributes': {'name': profile_name, 'profileType': 'IOS_APP_STORE'},
            'relationships': {
                'bundleId': {'data': {'type': 'bundleIds', 'id': bundle['id']}},
                'certificates': {'data': [{'type': 'certificates', 'id': state['certificate_id']}]}
            }}})['data']
    encoded_profile = profile['attributes']['profileContent']
    signed = cms.ContentInfo.load(base64.b64decode(encoded_profile))
    profile_plist = plistlib.loads(signed['content']['encap_content_info']['content'].native)
    entitlements = profile_plist['Entitlements']
    assert args.team_id in profile_plist['TeamIdentifier'], 'Wrong Apple team'
    assert entitlements['application-identifier'].endswith('.' + BUNDLE), 'Wrong Bundle ID'
    assert entitlements.get('com.apple.developer.healthkit'), 'HealthKit missing from profile'
    assert entitlements.get('com.apple.developer.kernel.increased-memory-limit'), 'Increased Memory Limit missing from profile'
    assert not entitlements.get('get-task-allow', False), 'Distribution profile required'
    values = {'ASC_KEY_ID': args.key_id, 'ASC_ISSUER_ID': args.issuer_id,
              'ASC_PRIVATE_KEY_B64': b64(args.key_file.read_bytes()),
              'IOS_DISTRIBUTION_P12_B64': state['p12'],
              'IOS_DISTRIBUTION_P12_PASSWORD': state['password'],
              'IOS_PROVISIONING_PROFILE_B64': encoded_profile}
    for name, value in values.items():
        github(args, 'secret', 'set', name, value=value)
    github(args, 'variable', 'set', 'APPLE_TEAM_ID', '--body', args.team_id)
    print('Apple distribution certificate/profile verified and six encrypted repository secrets configured.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'signing', 'connect'])
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--issuer-id', required=True)
    parser.add_argument('--team-id', required=True)
    parser.add_argument('--repository', default='Dhafen/priv-ai')
    parser.add_argument('--tester-email')
    args = parser.parse_args()
    owner = args.repository.split('/')[0]
    login = subprocess.check_output(['gh', 'api', 'user', '--jq', '.login'], text=True).strip()
    if owner.casefold() != login.casefold():
        raise SystemExit('Only configure a repository owned by the authenticated GitHub account')
    api = AppleAPI(args.key_file, args.key_id, args.issuer_id)
    bundles = api.request('bundleIds', query={'filter[identifier]': BUNDLE})['data']
    if not bundles:
        raise SystemExit('Register com.dhafen.privai and both capabilities in the Apple portal first')
    bundle = bundles[0]
    if args.action == 'signing':
        signing(args, api, bundle)
    elif args.action == 'connect':
        apps = api.request('apps', query={'filter[bundleId]': BUNDLE})['data']
        if not apps:
            raise SystemExit('Create the app record in App Store Connect first')
        app_id = apps[0]['id']
        groups = api.request('betaGroups', query={'filter[app]': app_id, 'limit': 200})['data']
        groups = [item for item in groups if item['attributes']['name'] == 'Priv AI Personal'
                  and item['attributes']['isInternalGroup']]
        if not groups:
            group = api.request('betaGroups', 'POST', {'data': {
                'type': 'betaGroups', 'attributes': {'name': 'Priv AI Personal',
                    'isInternalGroup': True, 'publicLinkEnabled': False, 'hasAccessToAllBuilds': True},
                'relationships': {'app': {'data': {'type': 'apps', 'id': app_id}}}}})['data']
        else:
            group = groups[0]
        if args.tester_email:
            testers = api.request('betaGroups/' + group['id'] + '/betaTesters')['data']
            if not any(item['attributes']['email'].casefold() == args.tester_email.casefold() for item in testers):
                raise SystemExit('Your Apple account must be added to the internal group before delivery')
        github(args, 'variable', 'set', 'APP_STORE_APP_ID', '--body', app_id)
        github(args, 'variable', 'set', 'TESTFLIGHT_INTERNAL_GROUP_ID', '--body', group['id'])
        print('App record and internal TestFlight group verified; repository variables configured.')
    else:
        capabilities = api.request('bundleIds/' + bundle['id'] + '/bundleIdCapabilities')['data']
        print(json.dumps({'bundle_id': BUNDLE, 'registered': True,
            'capabilities': [item['attributes']['capabilityType'] for item in capabilities]}, indent=2))


if __name__ == '__main__':
    main()
