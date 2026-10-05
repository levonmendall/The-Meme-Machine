import http.server
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import time

from meme_machine.operational import metrics

class MetricsIsolation(unittest.TestCase):
    def test_only_bounded_static_get_is_exposed(self):
        with tempfile.TemporaryDirectory() as td:
            body=('meme_machine_owner_action_required 0\nmeme_machine_monitor_heartbeat_seconds '+str(time.time())+'\n').encode()
            file=Path(td)/'metrics.prom';file.write_bytes(body)
            with patch.object(metrics,'FILE',file):
                server=http.server.HTTPServer(('127.0.0.1',0),metrics.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                url='http://127.0.0.1:'+str(server.server_address[1])
                try:
                    self.assertEqual(urllib.request.urlopen(url+'/metrics').read(),body+b'meme_machine_monitor_stale 0\n')
                    for req,code in ((urllib.request.Request(url+'/metrics',data=b'change',method='POST'),501),
                                     (url+'/../portfolio.sqlite',404)):
                        with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(req)
                        self.assertEqual(raised.exception.code,code)
                    self.assertEqual(file.read_bytes(),body)
                    file.write_bytes(b'x'*32769)
                    with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(url+'/metrics')
                    self.assertEqual(raised.exception.code,503)
                finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_monitor_death_cannot_leave_green_metrics(self):
        body=b'meme_machine_owner_action_required 0\nmeme_machine_monitor_heartbeat_seconds 1000\n'
        self.assertIn(b'meme_machine_owner_action_required 0',metrics.report(body,now=1100))
        self.assertIn(b'meme_machine_owner_action_required 1',metrics.report(body,now=1301))
        self.assertIn(b'meme_machine_monitor_stale 1',metrics.report(body,now=1301))

if __name__=='__main__':unittest.main()
