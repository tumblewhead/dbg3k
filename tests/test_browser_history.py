"""Real file-index/model checks plus a read-only fixed-asset server contract."""
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from dbg3k.history_browser import Handler, FILES
from test_kodama import sample

ROOT = Path(__file__).resolve().parents[1]


class BrowserHistoryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser domain/index checks')
    def test_actual_browser_decoder_and_streaming_file_index(self):
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / 'sample.json'
            fixture.write_text(json.dumps(sample()))
            result = subprocess.run(['node', str(ROOT / 'tests/browser_model_test.js'), str(fixture)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def request(self, path, host='127.0.0.1:8767'):
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = Message()
        handler.headers['Host'] = host
        handler.server = SimpleNamespace(server_port=8767)
        handler.wfile = BytesIO()
        headers, statuses = {}, []
        handler.send_response = lambda code: statuses.append(code)
        handler.send_error = lambda code, *args: statuses.append(code)
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        handler.do_GET()
        return statuses, headers, handler.wfile.getvalue()

    def test_fixed_assets_and_no_filesystem_or_upload_endpoint(self):
        for path in FILES:
            statuses, headers, body = self.request(path)
            self.assertEqual(statuses, [200], path)
            self.assertTrue(body)
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.request('/../../CONTINUE.md')[0], [404])
        self.assertEqual(self.request('/upload')[0], [404])
        self.assertEqual(self.request('/', host='example.com:8767')[0], [403])
        self.assertFalse(hasattr(Handler, 'do_POST'))
