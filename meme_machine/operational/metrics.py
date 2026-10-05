"""Localhost-only bounded read-only metrics for the existing DigitalOcean agent."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import re
import time

FILE=Path('/var/lib/meme-machine-monitor/meme_machine.prom')

def report(body,now=None):
    """A dead local monitor cannot leave a permanently green published flag."""
    text=body.decode('ascii')
    matches=re.findall(r'^meme_machine_monitor_heartbeat_seconds ([0-9.e+]+)$',text,re.M)
    if len(matches)!=1:raise ValueError('monitor heartbeat required')
    age=(time.time() if now is None else now)-float(matches[0])
    stale=age>300 or age < -60
    if stale:
        text=re.sub(r'^meme_machine_owner_action_required [01]$',
            'meme_machine_owner_action_required 1',text,flags=re.M)
    return (text+'meme_machine_monitor_stale '+str(int(stale))+'\n').encode('ascii')

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/metrics':self.send_error(404);return
        try:
            with FILE.open('rb') as stream:body=stream.read(32769)
            if len(body)>32768:raise ValueError('metrics bound')
            body=report(body)
        except (OSError,ValueError):self.send_error(503);return
        self.send_response(200);self.send_header('Content-Type','text/plain; version=0.0.4')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*_):pass

def main():
    server=HTTPServer(('127.0.0.1',9101),Handler);server.timeout=5
    try:server.serve_forever(poll_interval=.5)
    finally:server.server_close()

if __name__=='__main__':main()
