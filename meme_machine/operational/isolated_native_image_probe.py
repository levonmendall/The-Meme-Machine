"""Fixed offline copied-image proof; never a native market/parity acceptance."""
import ctypes
import importlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import signal
import resource
import sys
import threading

RUNNERS=('meme_machine.lanes.pump.runner','meme_machine.lanes.pump.pumpswap_survivor_runtime',
    'meme_machine.lanes.pons.pons_selective_cohort','meme_machine.lanes.pons.pons_survivor_runtime')
SOURCE=('meme_machine.runtime.evidence_worker','meme_machine.solana_selective_source',
        'meme_machine.solana_evidence_service')


def square(value):return value*value


def main():
    checks={}
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if (len(sys.argv)!=1 or os.getpid()!=1 or os.getppid()!=0 or Path.cwd()!=Path('/work/native')
            or sys.flags.no_site!=1 or status['NoNewPrivs'].strip()!='1'):
        raise ValueError('native_image_probe_context_required')
    checks['namespaced_pid1']=True
    checks['zero_capabilities']=all(int(status[key].strip(),16)==0 for key in
        ('CapEff','CapPrm','CapInh','CapBnd','CapAmb'))
    checks['no_new_privileges']=status['NoNewPrivs'].strip()=='1'
    checks['no_site']=('site' not in sys.modules and not list(Path('/image').rglob('*.pth'))
                       and not list(Path('/image').rglob('site-packages')))
    checks['private_python_paths']=(sys.executable=='/image/runtime/bin/python3.12'
        and sys.prefix==sys.base_prefix=='/image/runtime'
        and all(path=='/image/app' or path=='/image/deps' or path.startswith('/image/runtime/')
                for path in sys.path))
    checks['declared_image_proof_fd_limit']=resource.getrlimit(resource.RLIMIT_NOFILE)==(4096,4096)
    with os.fdopen(4,'rb') as facts:raw=facts.read(4097)
    if len(raw)>4096:raise ValueError('native_image_probe_fixture_bound')
    fixture=json.loads(raw)
    if type(fixture) is not dict or set(fixture)!={'schema','secret','unix','abstract','port','parent_pid','host_shm'}\
            or fixture['schema']!='nonfinancial-native-image-proof-v1':
        raise ValueError('native_image_probe_fixture_required')
    stopped=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    parent=socket.socket(fileno=3)
    parent.settimeout(2);parent.sendall(b'native image proof')
    checks['private_parent_ipc']=parent.recv(32)==b'parent acknowledged'
    def denied(name,action):
        try:action()
        except OSError:checks[name]=True
        else:checks[name]=False
    denied('host_secret_read',lambda:Path(fixture['secret']).read_bytes())
    denied('host_secret_write',lambda:Path(fixture['secret']).write_bytes(b'wrong'))
    denied('host_parent_proc',lambda:Path('/proc/'+str(fixture['parent_pid'])+'/environ').read_bytes())
    denied('oldroot_detached',lambda:Path('/oldroot').iterdir().__next__())
    denied('source_readonly',lambda:Path(__file__).write_bytes(b'wrong'))
    def connect(family,address):
        with socket.socket(family,socket.SOCK_STREAM) as peer:
            peer.settimeout(.2);peer.connect(address)
    denied('host_unix_path',lambda:connect(socket.AF_UNIX,fixture['unix']))
    denied('host_abstract_unix',lambda:connect(socket.AF_UNIX,'\0'+fixture['abstract']))
    denied('host_loopback_tcp',lambda:connect(socket.AF_INET,('127.0.0.1',fixture['port'])))
    checks['no_egress_interfaces']=socket.if_nameindex()==[(1,'lo')]
    checks['no_ipv4_routes']=not [line for line in Path('/proc/net/route').read_text().splitlines()
        if line.strip() and not line.startswith('Iface')]
    # Real runner/source imports only. No runner, source, book, Supervisor or
    # allocation constructor is called by this explicitly limited image proof.
    for module in (*RUNNERS,*SOURCE):importlib.import_module(module)
    checks['four_native_runner_imports']=all(name in sys.modules for name in RUNNERS)
    checks['native_source_imports']=all(name in sys.modules for name in SOURCE)
    for module in ('websockets','simdjson','grpc','google.protobuf','based58','typing_extensions'):
        value=importlib.import_module(module)
        if not str(value.__file__).startswith('/image/deps/'):
            raise ValueError('native_image_dependency_origin')
    checks['six_pinned_dependency_imports']=True
    with sqlite3.connect('/work/native/image-proof.sqlite') as database:
        database.execute('PRAGMA journal_mode=WAL');database.execute('PRAGMA synchronous=FULL')
        database.execute('CREATE TABLE proof(value INTEGER)');database.execute('INSERT INTO proof VALUES(42)')
        database.commit()
        checks['sqlite_FULL_WAL']=(database.execute('PRAGMA synchronous').fetchone()==(2,)
            and database.execute('PRAGMA journal_mode').fetchone()==('wal',)
            and database.execute('SELECT value FROM proof').fetchone()==(42,))
    database.close()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind('/work/native/proof.sock');server.listen(1)
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect('/work/native/proof.sock');connection,_=server.accept()
            with connection:peer.sendall(b'proof');checks['private_native_unix']=connection.recv(5)==b'proof'
    import concurrent.futures
    import multiprocessing
    context=multiprocessing.get_context('spawn');semaphore=context.Semaphore(1)
    checks['private_dev_shm']=(os.stat('/dev/shm').st_dev!=fixture['host_shm']
                              and bool(list(Path('/dev/shm').glob('sem.*'))))
    with concurrent.futures.ProcessPoolExecutor(max_workers=2,mp_context=context) as pool:
        checks['real_preparation_spawn_pool']=list(pool.map(square,[1,2,3,4]))==[1,4,9,16]
    parent.sendall(b'proof ready')
    if not stopped.wait(5):raise ValueError('native_image_probe_term_not_delivered')
    with sqlite3.connect('/work/native/image-proof.sqlite') as database:
        database.execute('PRAGMA synchronous=FULL')
        database.execute('INSERT INTO proof VALUES(43)');database.commit()
        checks['graceful_TERM_FULL_cleanup']=database.execute('SELECT value FROM proof ORDER BY value').fetchall()==[(42,),(43,)]
    database.close();parent.close()
    checks['all']=all(checks.values())
    print(json.dumps(dict(schema='isolated-native-image-proof-v1',status='ISOLATED_NATIVE_IMAGE_PROVEN'
        if checks['all'] else 'BLOCKED',checks=checks,financial_authority=False,provider_calls=0,
        native_runners_started=False,native_source_started=False,full_market_speed_proven=False,
        native_resource_profile_verified=False,proof_nofile_limit=4096,
        production_equivalent=False,actual_service_restrictions_verified=False)),flush=True)
    return 0 if checks['all'] else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        frames=[];frame=error.__traceback__
        while frame:
            frames.append(dict(module=frame.tb_frame.f_globals.get('__name__','unknown'),
                               function=frame.tb_frame.f_code.co_name,line=frame.tb_lineno))
            frame=frame.tb_next
        print(json.dumps(dict(schema='isolated-native-image-proof-v1',status='BLOCKED',
            code='native_image_probe_unavailable',error_type=type(error).__name__,frames=frames[-4:],
            financial_authority=False,provider_calls=0,actual_service_restrictions_verified=False)),flush=True)
        raise SystemExit(2)
