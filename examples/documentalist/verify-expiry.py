"""Exercise a disposable Documentalist checkout; it never contacts a real instance.

Run with PYTHONPATH=src python examples/documentalist/verify-expiry.py --documentalist PATH.
The checkout needs npm dependencies and a production build.
"""

import argparse
import http.cookiejar
import json
import os
import socket
import subprocess
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.request import HTTPCookieProcessor, Request, build_opener

from openguildkit import clock
from openguildkit.portal_verification import verify_portal
from openguildkit.storage import write_json

parser = argparse.ArgumentParser()
parser.add_argument('--documentalist', type=Path, required=True, help='Local Documentalist checkout with npm dependencies and build')
doc = parser.parse_args().documentalist.resolve()
with tempfile.TemporaryDirectory(prefix='ogk-expiry-integration-') as folder:
    root = Path(folder)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'DOCUMENTALIST_DATA_DIR': str(root / 'data'), 'DOCUMENTALIST_URL': origin,
           'DOCUMENTALIST_COOKIE_SECURE': 'false'}
    server = subprocess.Popen(['node', '--require', './scripts/windows-readlink.cjs', 'node_modules/next/dist/bin/next',
                               'start', '--port', str(port)], cwd=doc, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for _ in range(100):
            try:
                with client.open(origin + '/setup', timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('The local Documentalist server did not start')
        def api(path, payload=None, method=None):
            data = json.dumps(payload).encode() if payload is not None else None
            request = Request(origin + path, data=data, method=method,
                              headers={'Origin': origin, 'Content-Type': 'application/json'})
            with client.open(request, timeout=10) as response:
                return json.load(response)
        token = (root / 'data' / 'setup-token').read_text(encoding='utf-8').strip()
        api('/api/auth/setup', {'token': token, 'email': 'editor@example.org', 'name': 'Editor', 'password': 'temporary-test-pass-123'})
        api('/api/auth/login', {'email': 'editor@example.org', 'password': 'temporary-test-pass-123'})
        space = api('/api/spaces', {'name': 'Expiry interop'})['space']
        api('/api/spaces/' + space['id'], {'accessMode': 'magic_link'}, 'PATCH')
        future = (clock.real_now().date() + timedelta(days=1)).isoformat()
        past = (clock.real_now().date() - timedelta(days=1)).isoformat()
        setup = ("import { updateSpaceAllowedEmail } from './src/lib/store'; "
                 "(async () => { await updateSpaceAllowedEmail(process.argv[1], 'reader@example.org', true, process.argv[2]); })();")
        subprocess.run(['node', 'node_modules/tsx/dist/cli.mjs', '-e', setup, space['id'], future], cwd=doc,
                       env=env, capture_output=True, text=True, check=True)
        portal = f"{origin}/p/{space['slug']}"
        state = root / 'project' / '.openguildkit'
        share = {'id': 'one', 'recipients': ['reader@example.org'], 'until': future, 'portal': portal,
                 'revoked_at': None, 'deliverable': 'sample.md', 'by': 'CM'}
        def compare():
            with patch('sys.stdin.isatty', return_value=True), patch('getpass.getpass', return_value='temporary-test-pass-123'):
                return verify_portal(state, portal, 'editor@example.org')
        write_json(state / 'shares' / 'shares.json', {'shares': [share]})
        first = compare()
        assert first['source'] == 'documentalist-api' and first['rows'][0]['status'] == 'matches' and first['rows'][0]['policy_active'], first
        api('/api/spaces/' + space['id'] + '/access/invites', {'email': 'reader@example.org', 'expiresOn': past}, 'PATCH')
        write_json(state / 'shares' / 'shares.json', {'shares': [{**share, 'until': past}]})
        second = compare()
        assert second['source'] == 'documentalist-api' and second['rows'][0]['status'] == 'matches' and not second['rows'][0]['policy_active'], second
        print('Local portal: future and past dates match the register; source and state recorded.')
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
