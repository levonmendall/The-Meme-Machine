"""Bounded finalized Pump.fun log stream for prospective point-in-time evidence."""
from collections import deque
import json
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from websockets.sync.client import connect

from . import pump

WINDOW_SECONDS = 60
RETENTION_SECONDS = 75
MAX_EVENTS = 50_000


def websocket_url(http_url):
    parts=urlsplit(http_url)
    if parts.scheme != 'https' or not parts.netloc:
        raise ValueError('HTTPS RPC required')
    path = parts.path\n    if parts.hostname == 'solana.api.onfinality.io' and path.rstrip('/') == '/public':\n        path = '/public-ws'\n    return urlunsplit(('wss',parts.netloc,path,parts.query,parts.fragment))


class PumpTape:
    """In-memory finalized trade tape with explicit continuity/capacity truth."""
    def __init__(self, retention=RETENTION_SECONDS, max_events=MAX_EVENTS, clock=time.time):
        if retention < WINDOW_SECONDS or max_events < 1:
            raise ValueError('invalid tape bounds')
        self.retention,self.max_events,self.clock=retention,max_events,clock
        self._events=deque()
        self._lock=threading.Lock()
        self.sequence=0
        self.warm_since=None
        self.loss_until=0
        self.connected=False
        self.notifications=0
        self.trade_events=0
        self.gaps=0
        self.capacity_losses=0
        self.parse_failures=0