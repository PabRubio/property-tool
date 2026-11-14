"""Exercise the public form in Chrome without sending email or touching real records."""
import functools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(os.environ.get('LACEWING_TEST_ROOT', Path(__file__).resolve().parents[1]))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    chrome = os.environ.get('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        raise SystemExit('Chrome/Chromium is required; set CHROME_BIN to its executable.')
    with tempfile.TemporaryDirectory(prefix='lacewing-brief-delivery-') as temporary:
        folder = Path(temporary)
        handler = functools.partial(QuietHandler, directory=str(ROOT / 'web/public'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        profile = folder / 'chrome'
        browser = subprocess.Popen([
            chrome, '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
            '--disable-background-networking', '--remote-debugging-port=0',
            '--user-data-dir=' + str(profile), 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if (profile / 'DevToolsActivePort').exists():
                    break
                if browser.poll() is not None:
                    raise RuntimeError('Chrome exited before its debugging port became available')
                time.sleep(.1)
            port = (profile / 'DevToolsActivePort').read_text().splitlines()[0]
            runner = Path(__file__).with_suffix('.mjs')
            result = subprocess.run([
                'node', str(runner), port, str(server.server_port), str(folder), str(ROOT),
            ], timeout=120)
            if result.returncode:
                return result.returncode
            sys.path.insert(0, str(ROOT))
            from app import create_app
            with patch('app.default_provider', return_value='none'):
                app = create_app(folder / 'records')
                client = app.test_client()
                for name in ('property-brief', 'area-brief', 'commercial-retail', 'commercial-offices', 'commercial-industrial'):
                    brief = json.loads((folder / (name + '.json')).read_text())
                    response = client.post('/api/records', json={'inputs': brief['inputs']},
                                           headers={'X-Local-Token': app.csrf_token})
                    assert response.status_code == 201, response.get_json()
                    stored = response.get_json()['inputs']
                    assert stored['investor']['email'] == 'investor@example.com'
                    assert stored['enquiry']['kind'] == brief['inputs']['enquiry']['kind']
                    if name == 'property-brief':
                        assert stored['property']['asking_price'] == 250000
                        assert stored['assumptions']['monthly_rent'] == 1500
                    elif name == 'area-brief':
                        assert stored['enquiry']['area'] == 'Manchester'
                    else:
                        kind = name.split('-', 1)[1]
                        assert stored['property']['asset_class'] == 'commercial'
                        assert stored['property']['property_type'] == kind
                        assert stored['property']['floor_area_sqm'] == 150
                        assert stored['property']['floor_area_basis'] == ('nia' if kind == 'offices' else 'gia')
                        assert stored['property']['lease_years'] == 99
                        assert stored['property']['bedrooms'] is None
                        assert stored['assumptions']['annual_rent'] == 24000
                        assert stored['assumptions']['monthly_rent'] == 2000
                        assert stored['assumptions']['lease_remaining_months'] == 60
                        assert stored['assumptions']['break_month'] == 36
                        assert stored['assumptions']['business_rates_annual'] == 8000
                        assert stored['assumptions']['purchase_vat_pct'] == 20
                        assert stored['assumptions']['purchase_vat_recoverable_pct'] == 50
                print('PASS: residential, area and all three commercial email payloads import through the dashboard API with preserved values.')
            return 0
        finally:
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.terminate()
                browser.wait(timeout=10)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    sys.exit(main())
