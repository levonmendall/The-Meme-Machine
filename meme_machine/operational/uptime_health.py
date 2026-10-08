"""Public constant-size health status; no economic or credential access."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import re

from .metrics import FILE, report


def healthy(file=FILE):
    try:
        with file.open('rb') as stream:
            body = stream.read(32769)
        if len(body) > 32768:
            return False
        current = report(body).decode('ascii')
        flags = re.findall(r'^meme_machine_owner_action_required ([01])$', current, re.M)
        return flags == ['0']
    except (OSError, ValueError):
        return False


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def answer(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != '/healthz':
            self.answer(404, b'UNKNOWN\n')
        elif healthy():
            self.answer(200, b'OK\n')
        else:
            self.answer(503, b'OWNER_ACTION_REQUIRED\n')

    def log_message(self, *_):
        pass


def main():
    server = HTTPServer(('0.0.0.0', 9102), Handler)
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
