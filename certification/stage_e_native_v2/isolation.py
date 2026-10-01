"""Count attempted provider access and block it before any packet is sent."""
from contextlib import contextmanager, ExitStack
import socket
import subprocess
import urllib.request
from unittest.mock import patch


@contextmanager
def provider_firewall():
    attempts=[]
    def denied(kind):
        def fail(*args,**kwargs):
            attempts.append(kind)
            raise PermissionError('provider_call_attempt_forbidden:'+kind)
        return fail
    with ExitStack() as stack:
        for obj,name,kind in ((socket.socket,'connect','socket.connect'),
                              (socket.socket,'connect_ex','socket.connect_ex'),
                              (socket,'create_connection','socket.create_connection'),
                              (socket,'getaddrinfo','socket.getaddrinfo'),
                              (urllib.request,'urlopen','urllib.request.urlopen')):
            stack.enter_context(patch.object(obj,name,denied(kind)))
        yield attempts


@contextmanager
def child_firewall():
    """Trials have no arbitrary subprocess authority. An explicit child probe
    uses the same bootstrap/environment, with its own origin receipt, outside
    this context. Material entrypoints cannot escape via Python children.
    """
    def denied(*args,**kwargs):
        raise PermissionError('unbound_subprocess_entrypoint_forbidden')
    with patch.object(subprocess,'Popen',denied):
        yield
