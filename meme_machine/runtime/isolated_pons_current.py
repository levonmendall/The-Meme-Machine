"""Owned bookless bindings for the actual Pons Current cohort loop.

Provider acquisition remains native and parent mediated. A missing Nitro port
is a capability failure, never permission to substitute a sampled RPC clock.
No financial recovery, inception or copied epoch is supported by this context.
"""
import os
from pathlib import Path
import threading
import time
from weakref import WeakKeyDictionary

from meme_machine.runtime.isolated_native_bootstrap import require_runner_ports
from meme_machine.runtime.isolated_native_resources import require_resources
from meme_machine.runtime.journal import canonical

_owners=WeakKeyDictionary()
_owners_lock=threading.Lock()


def _claim_owner(resources):
    # The resource capability may be shared by four actual native regimes, but
    # two Current controllers must never consume the same native outbox.
    with _owners_lock:
        lease=_owners.setdefault(resources,threading.Lock())
        if not lease.acquire(blocking=False):
            raise ValueError('isolated_native_pons_current_already_owned')
        return lease


def unexercised_finance():
    return dict(status='UNEXERCISED',financial_book_constructed=False,
        financial_authority=False,held_protection='UNEXERCISED',fills='UNEXERCISED',
        settlement='UNEXERCISED',authoritative_readiness=False)


class PonsCurrentContext:
    def __init__(self,resources,ports,paths,*,endpoint):
        self.resources=require_resources(resources)
        self.ports=require_runner_ports(resources,ports)
        self.owner=threading.current_thread()
        self.root=resources.root/'pons-current'
        expected=dict(ROOT=self.root,REPORT=self.root/'report.json',
            SKILL_DB=self.root/'pons-selective-wallet-skill.sqlite',
            PROGRESS=self.root/'cohort-progress.json',ROWS_LOG=self.root/'candidate-rows.jsonl',
            QUALIFIERS_LOG=self.root/'qualifiers.jsonl',PROVIDER_LOG=self.root/'provider-sessions.jsonl',
            RECOVERY_LOG=self.root/'sequencer-recoveries.jsonl')
        if (set(paths)!=set(expected) or any(Path(paths[key])!=value for key,value in expected.items())
                or any(p.is_symlink() for value in expected.values() for p in (value,*value.parents))):
            raise ValueError('isolated_native_pons_current_paths')
        forbidden=('MM_PAPER_EPOCH','MM_PORTFOLIO_ACCOUNTING_DB','MM_PORTFOLIO_EPOCH_FILE',
            'MM_DIRECTIONAL_SLEEVE_DB','MM_NATIVE_GENESIS_CAPITAL')
        if (any(os.environ.get(key) for key in forbidden)
                or os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')!='1'):
            raise ValueError('isolated_native_pons_current_configuration')
        resources.facts.require_fresh('pons',int(resources.clock()))
        self.source=ports.rpc_port('pons','current').source
        if endpoint is not self.source:
            raise ValueError('isolated_native_pons_current_source')
        # Resolve every mandatory physical source capability before any native
        # store opens. No sampled RPC clock can substitute for the real feed.
        ports.rpc_port('pons','discovery')
        ports.rpc_port('pons','survivor')
        self._lease=_claim_owner(resources)
        self._startup=[]
        self._loop_entered=False
        self._drained=False
        try:
            self.feed=ports.pons_feed()
            self._startup.append(self.feed.close)
            self._open_owned()
        except BaseException:
            self.close()
            raise

    def _open_owned(self):
        resources=self.resources
        self.identity=dict(schema='isolated-pons-current-v1',scope=resources.facts.value()['scope'],
            source_commit=resources.facts.value()['source_commit'],
            source_tree=resources.facts.value()['source_tree'],
            endpoint_identity=self.source.endpoint_identity,financial_authority=False)
        self.root.mkdir(mode=0o700,exist_ok=True)
        marker=self.root/'.isolated-current-owner.json'
        if marker.is_symlink():raise ValueError('isolated_native_pons_current_owner')
        if marker.exists():
            if marker.read_text()!=canonical(self.identity):
                raise ValueError('isolated_native_pons_current_owner')
        else:
            # No preexisting native result is adopted just because its path is
            # inside a new namespace. A legitimate owner restart has this marker.
            if any(self.root.iterdir()):raise ValueError('isolated_native_pons_current_foreign_state')
            with marker.open('x') as sink:sink.write(canonical(self.identity))
        self.require_nonfinancial()
        self.plane=resources.pons_plane()
        self.require_nonfinancial()
        self.provenance='alchemy:'+self.source.endpoint_identity

    def startup_owned(self,value,close=None):
        self._startup.append(value.close if close is None else close)
        return value

    def enter_loop(self):
        # From this point the native loop owns its ordinary finite drain/close.
        self._loop_entered=True
        self._startup.clear()

    def close_startup(self):
        if self._loop_entered:return
        from meme_machine.runtime.sqlite_failure import preserving_cleanup
        while self._startup:
            with preserving_cleanup():self._startup.pop()()

    def drained(self):
        self._drained=True

    def close(self):
        self.close_startup()
        if (not self._loop_entered or self._drained) and self._lease is not None:
            self._lease.release();self._lease=None

    def require_nonfinancial(self):
        require_resources(self.resources)
        if self.owner is not threading.current_thread():
            raise ValueError('isolated_native_pons_current_owner')
        forbidden=list(self.root.glob('trial-*.sqlite*'))
        forbidden.extend(self.root/name for name in ('pons-selective-cohort-capital.sqlite',
            'portfolio.sqlite','shared-capital.sqlite','native-genesis.json'))
        if any(path.exists() or path.is_symlink() for path in forbidden):
            raise ValueError('isolated_native_unexpected_financial_continuation')
        plane=getattr(self,'plane',None)
        if plane is not None:
            with plane.lock:
                if plane.db.execute("SELECT 1 FROM runtime WHERE key LIKE 'native_position:%' LIMIT 1").fetchone():
                    raise ValueError('isolated_native_unexpected_financial_continuation')

    def restore(self,saved):
        self.require_nonfinancial()
        if saved is None:return None
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        result=saved.get('result') or {}
        if (not isinstance(result,dict) or result.get('isolated_native')!=self.identity
                or result.get('policy_hash')!=POLICY_HASH or result.get('qualifiers')
                or result.get('lifecycles') or type(saved.get('cursor')) is not int
                or result.get('cohort_accounting')!=unexercised_finance()):
            raise ValueError('isolated_native_unexpected_financial_continuation')
        if saved.get('phase')=='finalizing':
            # The ordinary cohort rollover retains native observation history
            # while granting the same bounded successor observation budget.
            result['started_at']=time.time()
            result.pop('ended_at',None);result.pop('summary',None)
            result['autonomous_observation_offset']=len(result.get('rows',[]))
        return result

    def report(self,result):
        self.require_nonfinancial()
        return dict(isolated_native=dict(self.identity),financial_authority=False,
            cohort_accounting=unexercised_finance(),authoritative_readiness=False,
            financial_handoff='UNEXERCISED',held_protection='UNEXERCISED',fills='UNEXERCISED',
            settlement='UNEXERCISED',retained_native_qualified_decisions=sum(
                (row.get('vector') or {}).get('current_threshold_pass') is True
                for row in result.get('rows',[])),
            qualification_sizing_receipt_hash=self.resources.facts.receipt_hash)
