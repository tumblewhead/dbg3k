"""Serve the read-only browser inspector. Selected trace files stay in the browser."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = Path(__file__).with_name('browser')
FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
         '/index.html': ('index.html', 'text/html; charset=utf-8'),
         '/style.css': ('style.css', 'text/css; charset=utf-8'),
         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
         '/model.js': ('model.js', 'text/javascript; charset=utf-8'),
         '/worker.js': ('worker.js', 'text/javascript; charset=utf-8')}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            self.send_error(403, 'Use the printed loopback URL')
            return
        entry = FILES.get(urlsplit(self.path).path)
        if entry is None:
            self.send_error(404)
            return
        data = (ASSETS / entry[0]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', entry[1])
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; "
                         "worker-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be 0..65535')
    try:
        with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
            print(f'dbg3k history: http://127.0.0.1:{server.server_port}', flush=True)
            print('Choose a JSONL in the browser. No GDB/QEMU is started; files are not uploaded.', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except OSError as exc:
        parser.exit(1, f'Cannot start history inspector: {exc}\nTry --port 8768\n')


if __name__ == '__main__':
    main()
