"""Bookless construction ports for the real native candidate consumers.

No Supervisor, copied epoch, financial book or source-recovery authority is
created here. The fixed contained bootstrap must separately run the actual
source owner and authenticate fresh sizing facts. Production constructors keep
their existing defaults. Kernel/source startup integration remains required.
"""
from pathlib import Path
import os
import threading
import time
from functools import wraps

from meme_machine.operational.child_transport import ChildChannel, ChildRPCPort
from meme_machine.runtime.isolated_native_resources import require_resources


class NativeRunnerPorts:
    """Fixed native read factories over this bootstrap's parent-issued aliases."""
    __slots__ = ('resources', 'channel', '_stores', '_lock', 'closed')

    def __init__(self, resources, channel):
        object.__setattr__(self, 'resources', require_resources(resources))
        if type(channel) is not ChildChannel or channel.closed:
            raise ValueError('isolated_native_parent_channel_required')
        object.__setattr__(self, 'channel', channel)
        object.__setattr__(self, '_stores', {})
        object.__setattr__(self, '_lock', threading.RLock())
        object.__setattr__(self, 'closed', False)

    def __setattr__(self, name, value):
        raise AttributeError('immutable_native_runner_ports')

    def rpc_port(self, lane, regime):
        require_resources(self.resources)
        if self.closed:
            raise ValueError('isolated_native_runner_ports_closed')
        if lane not in ('pump','pons') or regime not in ('current','survivor','discovery'):
            raise ValueError('isolated_native_read_role')
        operation = lane+'_discovery' if regime == 'discovery' else lane+'_'+regime+'_qualification'
        sources = [source for source in self.channel.sources.values() if source.operation == operation and source.read_class == 'native']
        if len(sources) != 1:
            raise ValueError('isolated_native_read_role_unavailable')
        return ChildRPCPort(self.channel, sources[0].alias)

    def source_rpc(self, priority, *, operation):
        require_runner_ports(self.resources,self)
        operations={'history_receipt':'pump_history_receipt',
            'recovery_restart':'pump_recovery_restart','unattributed':'pump_source_identity'}
        if type(priority) is not int or not 1<=priority<=6 or operation not in operations:
            raise ValueError('isolated_native_source_read_role')
        sources=[source for source in self.channel.sources.values()
            if source.family=='solana' and source.operation==operations[operation]
            and source.read_class=='solana_evidence_'+str(priority)]
        if len(sources)!=1:
            raise ValueError('isolated_native_source_read_role_unavailable')
        return ChildRPCPort(self.channel,sources[0].alias)

    def source_config(self):
        require_runner_ports(self.resources,self)
        from meme_machine.operational.source_ports import SourceIdentity,native_reference
        source=native_reference(self.channel,'yellowstone')
        if any(row.endpoint_identity!=source.endpoint_identity
                for row in self.channel.sources.values() if row.family=='solana'):
            raise ValueError('isolated_native_source_provider_disagreement')
        return SourceIdentity(source.endpoint_identity)

    def source_channel(self):
        require_runner_ports(self.resources,self)
        self.source_config()
        from meme_machine.operational.source_ports import NativeGrpcChannel
        return NativeGrpcChannel(self.channel)

    def source_websocket(self):
        require_runner_ports(self.resources,self)
        config=self.source_config()
        from meme_machine.operational.source_ports import NativeWebSocket
        websocket=NativeWebSocket(self.channel)
        if websocket.source.endpoint_identity!=config.identity:
            raise ValueError('isolated_native_source_provider_disagreement')
        return websocket

    def pump_rpc(self, regime, *, limit=240, pacer=None):
        from meme_machine.lanes.pump.solana_read_rpc import new_rpc
        port = self.rpc_port('pump',regime)
        with self._lock:
            if 'pump_immutable' not in self._stores:
                from meme_machine.lanes.pump.solana_immutable_rpc import ImmutableReads
                path=self.resources._unused_native_path('solana-port-broker.sqlite')
                self._stores['pump_immutable'] = ImmutableReads(path,
                    endpoint_identity=port.source.endpoint_identity)
                info=path.stat()
                self._stores['pump_path_identity']=(info.st_dev,info.st_ino)
            if 'pump_broker' not in self._stores:
                from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
                path=Path(self._stores['pump_immutable'].path)
                info=path.stat()
                if path.is_symlink() or (info.st_dev,info.st_ino)!=self._stores['pump_path_identity']:
                    raise ValueError('isolated_native_pump_cache_owner')
                self._stores['pump_broker'] = EvidenceBroker(path)
            reads, broker = self._stores['pump_immutable'], self._stores['pump_broker']
        if reads.endpoint != port.source.endpoint_identity:
            raise ValueError('isolated_native_pump_provider_changed')
        return new_rpc(limit=limit, pacer=pacer, parent_port=port,
            shared_reads=reads, evidence_broker=broker)

    def pons_rpc(self, regime, **bounds):
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        return configured_rpc(parent_port=self.rpc_port('pons',regime),
            immutable_store=self.pons_store(), **bounds)

    def pons_store(self):
        require_resources(self.resources)
        if self.closed:
            raise ValueError('isolated_native_runner_ports_closed')
        with self._lock:
            if 'pons_immutable' not in self._stores:
                from meme_machine.lanes.pons.immutable_rpc import EvidenceStore
                self._stores['pons_immutable'] = EvidenceStore(
                    self.resources._unused_native_path('pons-immutable.sqlite'))
            return self._stores['pons_immutable']

    def pons_feed(self):
        require_resources(self.resources)
        if self.closed:
            raise ValueError('isolated_native_runner_ports_closed')
        with self._lock:
            from meme_machine.lanes.pons.sequencer_feed import SequencerBlockClock
            source=self.rpc_port('pons','discovery').source
            stream=self.channel.native_open(source)
            try:
                feed=SequencerBlockClock(parent_stream=stream)
            except BaseException:
                stream.close()
                raise
            # Each restarted consumer earns a fresh native session and feed
            # state; only its separately authenticated canonical cursor survives.
            feeds=self._stores.setdefault('pons_feeds',[])
            feeds[:]=[old for old in feeds if not old._parent_stream.closed]
            feeds.append(feed)
            return feed

    def pump_evidence(self, owner):
        require_resources(self.resources)
        if owner not in ('pump','pump:survivor'):
            raise ValueError('isolated_native_evidence_consumer')
        path = self.resources.root/'solana-evidence.sqlite'
        for suffix in ('','-wal','-shm','.sock'):
            if Path(str(path)+suffix).is_symlink():
                raise ValueError('isolated_native_evidence_symlink')
        if not path.is_file():
            raise ValueError('isolated_native_source_owner_not_started')
        from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence
        return RuntimeEvidence(path, owner=owner, clock=self.resources.clock,
            native_resources=self.resources,native_ports=self)

    def close(self):
        # The bootstrap joins all actual native workers before releasing ports.
        # These are private caches; parent Budget/Admission/Governor remain live.
        with self._lock:
            if self.closed:
                return
            for name, value in self._stores.items():
                if name == 'pons_feeds':
                    for feed in value:
                        feed.close()
                elif name == 'pons_immutable':
                    value.db.close()
                elif name == 'pump_broker':
                    value.close()
            object.__setattr__(self, 'closed', True)


def require_runner_ports(resources, ports):
    resources = require_resources(resources)
    if (type(ports) is not NativeRunnerPorts or ports.resources is not resources
            or ports.closed or ports.channel.closed):
        raise ValueError('isolated_native_runner_ports_required')
    return ports


def validate_survivor_constructor(root, capital, run_id, lane, resources, ports):
    """Check explicit capability and paths before a mkdir or native store open."""
    resources = require_resources(resources)
    require_runner_ports(resources, ports)
    if (lane not in ('pump','pons') or capital is not None
            or Path(root) != resources.root/(lane+'-survivor')
            or run_id != resources.facts.value()['scope']):
        raise ValueError('isolated_native_survivor_construction')
    resources.facts.require_fresh(lane, int(resources.clock()))
    return resources


def survivor_constructor(lane):
    """Close partially constructed private native owners on the same thread."""
    def decorate(call):
        @wraps(call)
        def owned(runtime, *args, **kwargs):
            if kwargs.get('native_resources') is None:
                return call(runtime,*args,**kwargs)
            try:
                return call(runtime,*args,**kwargs)
            except BaseException:
                resources=getattr(runtime,'native_resources',None)
                if resources is not None:
                    from meme_machine.runtime.sqlite_failure import preserving_cleanup
                    with preserving_cleanup():
                        close_bookless_runtime(runtime,lane)
                raise
        return owned
    return decorate


def close_bookless_runtime(runtime, lane):
    resources = require_resources(runtime.native_resources)
    # These owners were created on the native executor. A failed constructor
    # cannot leave an off-thread SQLite handle for the parent to close later.
    history = getattr(runtime,'candidate_history',None)
    if history is not None:
        resources.require_history(history)
        history.close()
        runtime.candidate_history=None
    history = getattr(runtime,'history',None)
    if history is not None:
        resources.release_survivor_history(history,lane)
        runtime.history=None
    sleeve = getattr(runtime,'sleeve',None)
    if sleeve is not None:
        resources.require_observation_state(sleeve,lane)
        sleeve.close()
        runtime.sleeve=None
    if lane == 'pump':
        plane = getattr(runtime,'plane',None)
        if plane is not None:
            plane.close()
            runtime.plane=None


def require_bookless_runtime(runtime, lane):
    """An isolated candidate restart must never become financial recovery."""
    from meme_machine.runtime.isolated_native_admission import require_survivor_resources
    resources = require_survivor_resources(runtime, lane)
    if resources is None:
        return None
    require_runner_ports(resources, runtime.native_ports)
    resources.facts.require_fresh(lane, int(resources.clock()))
    for row in runtime.history.rows(include_retired=True):
        if (row.get('position') or row.get('pending_action') or row.get('reservation')
                or row.get('state') in ('reserved','filled','runner','exit_pending','open')):
            raise ValueError('isolated_native_unexpected_financial_continuation')
    if lane == 'pons':
        with runtime.plane.lock:
            if runtime.plane.db.execute("SELECT 1 FROM runtime WHERE key LIKE 'native_position:%' LIMIT 1").fetchone():
                raise ValueError('isolated_native_unexpected_financial_continuation')
    return resources


def maintain_bookless_runtime(runtime, lane):
    resources = require_bookless_runtime(runtime, lane)
    if resources is None:
        return False
    if time.monotonic() < getattr(runtime,'_next_isolated_maintenance',0):
        return True
    # This is the same actual history prefix reducer. Financial checkpoint and
    # terminal-book compaction have no scope because no book was constructed.
    from meme_machine.runtime.survivor_history import compact_restored_history
    if lane == 'pump':
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
    else:
        reduce_reset_history = None
    compact_restored_history(runtime.history, lane=lane, reducer=reduce_reset_history)
    runtime._next_isolated_maintenance=time.monotonic()+60
    return True


def observation_rallies(state, *, limit=256):
    """Use the native read-only rally reporter without a financial archive."""
    from meme_machine.runtime.sleeve_reservations import SleeveReservations
    # Its only archive dependency is the optional retired-outcome summary. An
    # explicit local facade supplies absence, never a fabricated financial book.
    class ReadOnlyRallies:
        db, lock = state.db, state.lock
        def _archive(self):
            return None
    return SleeveReservations.rally_report(ReadOnlyRallies(), limit=limit)


def bookless_report(runtime, lane):
    resources = require_bookless_runtime(runtime, lane)
    if resources is None:
        raise ValueError('isolated_native_runtime_required')
    history=getattr(runtime,'candidate_history',None)
    if history is None:
        # Pons opens this shared publication reader lazily. Bind its actual
        # owner connection so native shutdown releases it on the same worker.
        history=runtime.candidate_history=resources.candidate_history()
    resources.require_history(history)
    verification = runtime.sleeve.verify_observations()
    return dict(
        scope=resources.facts.value()['scope'], financial_authority=False,
        accounting=dict(status='UNEXERCISED', financial_book_constructed=False),
        accounting_replay=dict(status='UNEXERCISED', financial_book_constructed=False),
        sleeve=dict(status='NONFINANCIAL_OBSERVATION_ONLY', verification=verification),
        durable_handoff=False, financial_handoff='UNEXERCISED',
        held_protection='UNEXERCISED', fills='UNEXERCISED', settlement='UNEXERCISED',
        native_execution_cost=None,
        policies=runtime.sleeve.identity['policies'],
        rally_lifecycles=observation_rallies(runtime.sleeve),
        candidate_history=history.telemetry(),
        qualification_sizing_receipt_hash=resources.facts.receipt_hash)


class PumpCurrentContext:
    """Bind the actual Current globals to this owner's private native stores.

    Existing module-level path selection is validated before any open; it does
    not select no-allocation authority. That capability is explicitly required.
    """
    def __init__(self, resources, ports, *, report_path):
        self.resources = require_resources(resources)
        self.ports = require_runner_ports(resources, ports)
        self.owner = threading.get_ident()
        self.report_path = Path(report_path)
        if self.report_path != resources.root/'pump-current'/'report.json':
            raise ValueError('isolated_native_current_path')
        forbidden = ('MM_PAPER_EPOCH','MM_PORTFOLIO_ACCOUNTING_DB','MM_PORTFOLIO_EPOCH_FILE',
            'MM_DIRECTIONAL_SLEEVE_DB','MM_NATIVE_GENESIS_CAPITAL')
        expected = {'MM_SOLANA_CANDIDATE_HISTORY_DB':resources.root/'candidate-history.sqlite',
            'MM_SOLANA_EVIDENCE_PLANE_DB':resources.root/'solana-evidence.sqlite',
            'MM_SOLANA_EVIDENCE_BROKER_DB':resources.root/'solana-broker.sqlite'}
        if (any(os.environ.get(key) for key in forbidden)
                or any(os.environ.get(key) != str(value) for key,value in expected.items())
                or os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED') != '1'):
            raise ValueError('isolated_native_current_configuration')
        resources.facts.require_fresh('pump', int(resources.clock()))
        self.report_path.parent.mkdir(mode=0o700)
        self.history = resources.candidate_history()
        self.pipeline = None
        self.plane = None
        self.fill_context = None

    def require(self, resources, *, accounting, pipeline, history, fill_context):
        if (self.resources is not resources or self.owner != threading.get_ident()
                or accounting is not None or history is not self.history
                or pipeline is not self.pipeline or fill_context is not self.fill_context):
            raise ValueError('isolated_native_current_owner')
        resources.require_history(history)
        if pipeline is not None:
            path = pipeline.db.execute('PRAGMA database_list').fetchone()[2]
            if Path(path) != self.report_path.with_suffix('.pipeline.sqlite'):
                raise ValueError('isolated_native_current_pipeline_owner')
        if fill_context is not None and (fill_context.get('plane') is not self.plane
                or fill_context.get('pending') or fill_context.get('active')):
            raise ValueError('isolated_native_unexpected_financial_continuation')
        return resources
