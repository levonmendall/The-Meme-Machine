"""Short, serialized native boundary writes to the existing shared accountant.

All native books keep their economic rules. Reserve precedes a native fill;
delivery follows its durable commit. A retained pending event is redelivered at
recovery only after its native journal has proved the matching commit.
"""
from contextlib import contextmanager
import json
from pathlib import Path

from meme_machine.portfolio_accounting import PortfolioAccounting, PortfolioIntegrityError, canonical
from meme_machine.portfolio_lane_integration import LaneEvent, PortfolioLaneProducer


class NativePortfolio:
    def __new__(cls,database,lane):
        if cls is NativePortfolio:
            from meme_machine.shared_capital.runtime import selected,SharedNativePortfolio
            if selected(database):return SharedNativePortfolio(database,lane)
        return super().__new__(cls)

    def __init__(self, database, lane):
        self.database = Path(database)
        self.lane = lane
        if lane not in ("pump", "pons", "meteora", "ramses"):
            raise ValueError("unknown_lane")

    @contextmanager
    def writer(self):
        account = PortfolioAccounting(self.database, wait_for_writer=True)
        try:
            binding = account.binding()
            if binding is None:
                raise PortfolioIntegrityError("portfolio_not_initialized")
            producer = PortfolioLaneProducer(account, epoch_id=binding["receipt"]["epoch_id"], inception_sha256=binding["inception_sha256"])
            yield account, producer
        finally:
            account.close()

    def equity(self):
        with self.writer() as (account, _):
            return account.sleeve_equity(self.lane)

    def _alias(self, account, native):
        if not isinstance(native, str) or not native or len(native) > 2048:
            raise ValueError("native_identity_required")
        existing=account.db.execute('SELECT id FROM portfolio_native_ids WHERE lane=? AND native=?',(self.lane,native)).fetchone()
        if existing:return 'n'+str(existing[0])
        from meme_machine.runtime.lifecycle_identity import parsed
        issued=parsed(native)
        if issued and issued['index']<=account.snapshot().get('retired_native_through',{}).get(self.lane,0):
            raise PortfolioIntegrityError('retired_native_lifecycle_replay')
        account.db.execute("INSERT OR IGNORE INTO portfolio_native_ids(lane,native) VALUES(?,?)", (self.lane, native))
        return "n" + str(account.db.execute("SELECT id FROM portfolio_native_ids WHERE lane=? AND native=?", (self.lane, native)).fetchone()[0])

    def prepare(self, native, *, event_key, journal_hash, kind, at, data, value_evidence=None):
        """Persist one exact delivery intent; no native economic mutation occurs."""
        with self.writer() as (account, producer):
            from .operating_families import require_active,operational
            require_active(self.lane,production=operational() or
                           producer.epoch_id.startswith('paper-'))
            alias = self._alias(account, native)
            pending = account.db.execute("SELECT body FROM portfolio_native_pending WHERE lane=? AND native=?", (self.lane, native)).fetchone()
            if pending:
                event = LaneEvent(**json.loads(pending[0]))
                if event.native_event_id != event_key:
                    raise PortfolioIntegrityError("prior_native_delivery_requires_reconciliation")
                if event.kind != kind or event.data != data or event.native_journal_hash != journal_hash or event.value_evidence != value_evidence:
                    raise PortfolioIntegrityError("conflicting_native_delivery_intent")
                return event
            sequence = producer._native_cursors.get((self.lane, alias), 0) + 1
            tentative=LaneEvent(producer.epoch_id,self.lane,alias,event_key,sequence,journal_hash,kind,at,data,value_evidence)
            existing=account.canonical_event(producer._event_id(tentative))
            if existing:
                sequence=existing['body']['data']['provenance']['native_sequence']
                at=existing['body']['at']
            # Native observation clocks stay in their own journal. Serialized
            # shared publication time cannot regress behind another lane.
            from meme_machine.portfolio_accounting import _stamp
            last_at=account.snapshot()["last_at"]
            if _stamp(at)<_stamp(last_at):at=last_at
            if kind=='mark' and data.get('state')=='CURRENT' and value_evidence:
                value_evidence=dict(value_evidence,as_of=at)
            event = LaneEvent(producer.epoch_id, self.lane, alias, event_key, sequence, journal_hash, kind, at, data, value_evidence)
            body = canonical(event.canonical_value())
            # The pending fact is durably stored before any native commit. Native
            # reserve is also reflected globally before that commit can consume it.
            account.db.execute("INSERT INTO portfolio_native_pending VALUES(?,?,?)", (self.lane, native, body))
            if kind in ("reserve", "rebalance_reserve"):
                try:
                    producer.deliver(event)
                except BaseException:
                    account.db.execute("DELETE FROM portfolio_native_pending WHERE lane=? AND native=?", (self.lane, native))
                    raise
            return event

    def committed(self, native, *, event_key, journal_hash):
        """Called after native COMMIT or by verified native-journal recovery."""
        with self.writer() as (account, producer):
            row = account.db.execute("SELECT body FROM portfolio_native_pending WHERE lane=? AND native=?", (self.lane, native)).fetchone()
            if row is None:
                return None
            event = LaneEvent(**json.loads(row[0]))
            if event.native_event_id != event_key or event.native_journal_hash != journal_hash:
                raise PortfolioIntegrityError("native_commit_does_not_match_pending_delivery")
            result = producer.deliver(event)
            account.db.execute("DELETE FROM portfolio_native_pending WHERE lane=? AND native=?", (self.lane, native))
            return result

    def pending(self):
        with self.writer() as (account, _):
            return [(native, LaneEvent(**json.loads(body))) for native, body in account.db.execute("SELECT native,body FROM portfolio_native_pending WHERE lane=?", (self.lane,))]

    def deliver(self, native, **fact):
        """For an already verified native fact (replay and read-only marks)."""
        event = self.prepare(native, **fact)
        return self.committed(native, event_key=event.native_event_id, journal_hash=event.native_journal_hash)
