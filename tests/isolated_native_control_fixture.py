"""Actual native command service; no sampled market or fabricated command ACK."""
import asyncio
from types import SimpleNamespace

from meme_machine.operational.source_ports import SourceIdentity
from meme_machine.solana_evidence_service import serve


async def start_command_source(case):
    ready = asyncio.Event()
    stopped = asyncio.Event()
    resources, ports = case.resources, case.ports

    class Driver:
        native_resources = resources
        native_ports = ports
        pipeline_metrics = {}

        async def __call__(self, work, stop):
            self.work = work
            ready.set()
            await stop.wait()

    driver = Driver()
    # There is no provider call in this fixture. The real owner, SQLite schema,
    # handler, receipt transaction and spawned preparation probes are unchanged.
    repair = SimpleNamespace(_native_resources=resources, _native_ports=ports,
        config=SourceIdentity(ports.rpc_port('pump', 'current').source.endpoint_identity))
    task = asyncio.create_task(serve(resources.root/'solana-evidence.sqlite', None,
        repair_rpc=repair, stop=stopped, source_driver=driver,
        native_resources=resources, native_ports=ports))
    consumed = False

    async def close():
        nonlocal consumed
        if consumed:return
        try:
            stopped.set()
            await asyncio.wait_for(task, 10)
        finally:
            if task.done():consumed = True

    case.addAsyncCleanup(close)
    async with asyncio.timeout(10):
        while not ready.is_set():
            if task.done():
                task.result()
            await asyncio.sleep(.005)
    return driver, close
