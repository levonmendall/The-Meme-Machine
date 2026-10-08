"""Exercise the real IPC callback where the executor disallows bind(2)."""
import asyncio
from contextlib import contextmanager
import io
import os
from pathlib import Path
import socket
import threading
from unittest.mock import patch


@contextmanager
def ipc_transport():
    if os.environ.get('MM_REAL_IPC_TESTS')=='1':
        yield None;return
    loop=asyncio.get_running_loop();state={};real_socket=socket.socket
    class Server:
        def close(self):pass
        async def wait_closed(self):pass
    async def start(callback,*,path,**kwargs):
        state['callback']=callback;Path(path).touch();return Server()
    class Client:
        def __init__(self):self.timeout=None;self.closed=False;self.response=None;self.ready=threading.Event()
        def settimeout(self,value):self.timeout=value
        def connect(self,path):
            if 'callback' not in state:raise ConnectionRefusedError()
        def sendall(self,data):
            client=self
            class Reader:
                async def readline(self):return data
            class Stream:
                def write(self,reply):
                    if client.closed:raise BrokenPipeError()
                    client.response=reply;client.ready.set()
                async def drain(self):
                    if client.closed:raise ConnectionResetError()
                def close(self):pass
                async def wait_closed(self):pass
            asyncio.run_coroutine_threadsafe(state['callback'](Reader(),Stream()),loop)
        def makefile(self,*args):return self
        def readline(self,limit):
            if not self.ready.wait(self.timeout):raise TimeoutError()
            return self.response[:limit]
        def close(self):self.closed=True
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    def factory(family=socket.AF_INET,*args,**kwargs):
        return Client() if family==socket.AF_UNIX else real_socket(family,*args,**kwargs)
    with patch('asyncio.start_unix_server',side_effect=start),patch('socket.socket',side_effect=factory):yield state
