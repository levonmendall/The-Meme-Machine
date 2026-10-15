import http.server
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from meme_machine.operational import uptime_health


class UptimeHealthIsolation(unittest.TestCase):
    def test_persistent_action_or_dead_monitor_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td)/'monitor.prom'
            now = time.time()
            for flag, heartbeat, expected in (('0', now, True), ('1', now, False),
                                             ('0', now-301, False), ('0', now+61, False)):
                file.write_text('meme_machine_owner_action_required '+flag+'\n'
                                'meme_machine_monitor_heartbeat_seconds '+str(heartbeat)+'\n')
                self.assertEqual(uptime_health.healthy(file), expected)
            for body in (b'', b'x'*32769,
                         b'meme_machine_owner_action_required 0\n',
                         b'\xff',
                         ('meme_machine_owner_action_required 0\n'*2+
                          'meme_machine_monitor_heartbeat_seconds '+str(now)+'\n').encode()):
                file.write_bytes(body)
                self.assertFalse(uptime_health.healthy(file))
            file.unlink()
            self.assertFalse(uptime_health.healthy(file))

    def test_endpoint_exposes_only_constant_status_and_cannot_mutate_input(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td)/'monitor.prom'
            body = ('meme_machine_owner_action_required 0\n'
                    'meme_machine_monitor_heartbeat_seconds '+str(time.time())+'\n'
                    '# PRIVATE_SENTINEL_MUST_NOT_BE_EXPOSED\n').encode()
            file.write_bytes(body)
            read_health = uptime_health.healthy
            with patch.object(uptime_health, 'healthy', side_effect=lambda: read_health(file)):
                server = http.server.HTTPServer(('127.0.0.1', 0), uptime_health.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = 'http://127.0.0.1:'+str(server.server_address[1])
                try:
                    response = urllib.request.urlopen(url+'/healthz')
                    self.assertEqual(response.read(), b'OK\n')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    for request, code in ((url+'/../portfolio.sqlite', 404),
                                          (urllib.request.Request(url+'/healthz', data=b'change', method='POST'), 501)):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request)
                        self.assertEqual(raised.exception.code, code)
                    self.assertEqual(file.read_bytes(), body)
                    file.write_text('meme_machine_owner_action_required 1\n'
                                    'meme_machine_monitor_heartbeat_seconds '+str(time.time())+'\n')
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(url+'/healthz')
                    self.assertEqual(raised.exception.code, 503)
                    self.assertEqual(raised.exception.read(), b'OWNER_ACTION_REQUIRED\n')
                finally:
                    server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
