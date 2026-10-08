"""Finite Pump capability limits. Application bytes are never billed-byte claims."""
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import resource
import threading
import time

MIB = 1024 * 1024
MAX_STORAGE_ENTRIES = 256


class CapabilityStop(RuntimeError):
    """A fixed reason code, safe to put in a public failure receipt."""


@dataclass(frozen=True)
class Limits:
    wall_seconds: float = 60
    paired_seconds: float = 45
    shutdown_seconds: float = 2
    receive_stop: int = 48 * MIB
    stopping_ceiling: int = 64 * MIB
    cancellation_reserve: int = 64 * MIB
    frame_bytes: int = 16 * MIB
    storage_stop: int = 224 * MIB
    storage_bytes: int = 256 * MIB
    rss_bytes: int = 512 * MIB
    channels: int = 1
    native_rpcs: int = 3
    ws_connections: int = 1
    http_requests: int = 5
    http_cu: int = 90
    physical_methods: int = 11
    native_writes: int = 3
    ping_writes: int = 12
    ws_subscribes: int = 2
    ws_unsubscribes: int = 1
    records: int = 100000

    def __post_init__(self):
        # A caller may tighten a limit for a test, never enlarge the experiment.
        maximum = dict(wall_seconds=60, paired_seconds=45, shutdown_seconds=2,
                       receive_stop=48*MIB, stopping_ceiling=64*MIB,
                       cancellation_reserve=64*MIB, frame_bytes=16*MIB,
                       storage_stop=224*MIB, storage_bytes=256*MIB, rss_bytes=512*MIB,
                       channels=1, native_rpcs=3, ws_connections=1, http_requests=5,
                       http_cu=90, physical_methods=11, native_writes=3, ping_writes=12,
                       ws_subscribes=2, ws_unsubscribes=1, records=100000)
        durations = {'wall_seconds', 'paired_seconds', 'shutdown_seconds'}
        if any(type(v) not in ((int, float) if k in durations else (int,)) or not 0 < v <= maximum[k]
               for k, v in asdict(self).items()):
            raise ValueError('capability_limit_enlargement_or_invalid')
        if not (self.paired_seconds < self.wall_seconds and
                self.receive_stop <= self.stopping_ceiling and
                self.storage_stop < self.storage_bytes):
            raise ValueError('capability_limit_order')


def tree_bytes(root):
    total = 0
    for count, path in enumerate(Path(root).rglob('*'), 1):
        if count > MAX_STORAGE_ENTRIES:
            raise CapabilityStop('storage_inventory_bound')
        if path.is_symlink():
            raise CapabilityStop('disposable_storage_symlink')
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue  # SQLite can remove a WAL during this inventory.
        if path.is_file():
            total += max(stat.st_size, stat.st_blocks * 512)
    return total


class Budget:
    def __init__(self, out, *, limits=Limits(), clock=time.monotonic, stop=None):
        self.out, self.limits, self.clock = Path(out), limits, clock
        self.started = clock()
        self.stop = stop or threading.Event()
        self.lock = threading.RLock()
        self.counts, self.bytes = Counter(), Counter()
        self.failures = []
        self.shutdown_at = None
        self.stopping_bytes = None
        self.peak_rss = 0
        self.peak_storage = 0

    def fail(self, reason):
        with self.lock:
            if reason not in self.failures:
                self.failures.append(reason)
            self.stop.set()
        raise CapabilityStop(reason)

    def shutdown(self):
        with self.lock:
            self.stop.set()
            if self.shutdown_at is None:
                self.shutdown_at = self.clock()

    def claim(self, resource_name, *, physical=False):
        with self.lock:
            if self.stop.is_set():
                self.fail('request_after_stop')
            if self.clock() - self.started >= self.limits.wall_seconds:
                self.fail('wall_deadline')
            if resource_name not in ('channels', 'native_rpcs', 'ws_connections',
                                     'native_writes', 'ping_writes', 'ws_subscribes', 'ws_unsubscribes'):
                self.fail('unplanned_resource')
            if self.counts[resource_name] >= getattr(self.limits, resource_name):
                self.fail(resource_name + '_bound')
            if physical and self.counts['physical_methods'] >= self.limits.physical_methods:
                self.fail('physical_methods_bound')
            self.counts[resource_name] += 1
            self.counts['physical_methods'] += int(physical)

    def http(self, method, params):
        with self.lock:
            allowed = (method == 'getGenesisHash' and params == [] or
                       method == 'getSlot' and params == [{'commitment': 'finalized'}])
            if not allowed:
                self.fail('http_method_or_params_forbidden')
            if self.stop.is_set():
                self.fail('request_after_stop')
            if self.clock() - self.started >= self.limits.wall_seconds:
                self.fail('wall_deadline')
            if self.counts['http_requests'] >= self.limits.http_requests:
                self.fail('http_requests_bound')
            if self.counts['http:' + method] >= (1 if method == 'getGenesisHash' else 4):
                self.fail('http_method_count_bound')
            cu = 10 if method == 'getGenesisHash' else 20
            if self.counts['http_cu'] + cu > self.limits.http_cu:
                self.fail('http_cu_bound')
            if self.counts['physical_methods'] >= self.limits.physical_methods:
                self.fail('physical_methods_bound')
            self.counts.update(http_requests=1, http_cu=cu, physical_methods=1)
            self.counts['http:' + method] += 1

    def receive(self, transport, raw, capture):
        """Charge BEFORE decode; even a stopping/oversized/trailing frame counts.

        Capture executes before the threshold exception. Oversized frames retain
        their size receipt instead of defeating the archive frame bound.
        """
        with self.lock:
            trailing = self.stop.is_set()
            size = len(raw)
            self.bytes[transport] += size
            self.bytes['total_application'] += size
            self.counts['records'] += 1
            if transport in ('websocket', 'yellowstone'):
                self.bytes['streaming'] += size
                if trailing:
                    self.bytes['cancellation'] += size
            elif transport != 'http':
                self.fail('unknown_receive_transport')
            # Capture metadata is written even if the record/frame budget fails.
            capture(raw if size <= self.limits.frame_bytes else None, size, trailing)
            if size > self.limits.frame_bytes:
                self.fail('frame_bytes_bound')
            if self.counts['records'] > self.limits.records:
                self.fail('record_count_bound')
            if transport == 'websocket':
                # Published Solana WS tariff, rounded UP; no native CU fiction.
                self.counts['ws_published_cu_ceiling'] = (self.bytes['websocket'] + 4999) // 5000
                if self.counts['ws_published_cu_ceiling'] > 26844:
                    self.fail('ws_cu_reserve_bound')
            if self.bytes['cancellation'] > self.limits.cancellation_reserve:
                self.fail('cancellation_reserve_bound')
            if self.bytes['streaming'] > self.limits.stopping_ceiling + self.limits.cancellation_reserve:
                self.fail('observed_payload_ceiling')
            if not trailing and self.bytes['streaming'] >= self.limits.receive_stop:
                self.stopping_bytes = self.bytes['streaming']
                if self.stopping_bytes > self.limits.stopping_ceiling:
                    self.fail('stopping_frame_ceiling')
                self.shutdown()
                self.fail('received_byte_stop_threshold')

    def resources(self, *, rss=None, storage=None, shutdown=False):
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 if rss is None else rss
        storage = tree_bytes(self.out) if storage is None else storage
        self.peak_rss = max(self.peak_rss, rss)
        self.peak_storage = max(self.peak_storage, storage)
        if rss > self.limits.rss_bytes:
            self.fail('rss_budget')
        if storage > self.limits.storage_bytes:
            self.fail('storage_hard_budget')
        if not shutdown and storage >= self.limits.storage_stop:
            self.shutdown()
            self.fail('storage_stop_threshold')
        if not shutdown and self.clock() - self.started >= self.limits.wall_seconds:
            self.shutdown()
            self.fail('wall_deadline')
        if shutdown and self.shutdown_at is not None and self.clock() - self.shutdown_at > self.limits.shutdown_seconds:
            self.fail('shutdown_deadline')

    def snapshot(self):
        with self.lock:
            return dict(limits=asdict(self.limits), initiations=dict(self.counts),
                        storage_inventory_entry_limit=MAX_STORAGE_ENTRIES,
                        received_application_bytes=dict(self.bytes), failures=list(self.failures),
                        stopping_frame_total=self.stopping_bytes, peak_rss_bytes=self.peak_rss,
                        peak_storage_bytes=self.peak_storage,
                        wall_seconds=self.clock()-self.started,
                        protocol_overhead='UNMEASURED', billed_traffic='UNVERIFIED',
                        native_compute_units='NOT_CONVERTED_FROM_BYTES')
