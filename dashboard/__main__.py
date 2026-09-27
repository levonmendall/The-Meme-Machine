"""Loopback preview/observer. Does not start the paper runtime."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .api import Dashboard
from .model import Reader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--inception')
    parser.add_argument('--accounting')
    parser.add_argument('--telemetry')
    parser.add_argument('--fixture-dir', help='Explicit isolated development fixtures only')
    args = parser.parse_args()
    if args.fixture_dir and any((args.inception, args.accounting, args.telemetry)):
        parser.error('fixture mode cannot read canonical paths')
    mode = 'canonical'
    if args.fixture_dir:
        root = Path(args.fixture_dir)
        args.inception, args.accounting, args.telemetry = root/'inception.json', root/'accounting.json', root/'telemetry.json'
        mode = 'fixture'
    reader = Reader(args.inception, args.accounting, args.telemetry,
                    Path(__file__).resolve().parents[1]/'certification/sources.json', mode=mode)
    if mode == 'fixture':
        from .fixtures import FIXTURE_NOW
        reader.clock = lambda: FIXTURE_NOW
    app = Dashboard(reader)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not app.serve(self):
                self.send_error(404)
        do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Read-only {mode} observer: http://127.0.0.1:{server.server_port}/dashboard', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
