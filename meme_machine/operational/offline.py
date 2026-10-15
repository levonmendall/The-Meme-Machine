"""Explicit mocked native providers and isolated fixture state; zero network I/O.

This path exercises the real native journals and shared accounting. Fixture fills
are mechanics tests, and provide no claim of natural qualification or P&L.
"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import time

from meme_machine.runtime.native_boundary import NativeBoundary
from meme_machine.runtime.usd_valuation import USDValue
from meme_machine.runtime.lifecycle_identity import issue


def install_network_guard():
    import socket,urllib.request
    def forbidden(*args,**kwargs):raise RuntimeError('market I/O is forbidden in offline mode')
    forbidden.meme_machine_offline=True
    socket.create_connection=forbidden
    socket.socket.connect=forbidden
    socket.socket.connect_ex=forbidden
    urllib.request.urlopen=forbidden


class MockProvider:
    def __init__(self,lane):self.lane=lane;self.calls=0
    def value(self,now):
        self.calls+=1
        # Explicit fixture conversion, never installed in a production reader.
        return USDValue('fixture-'+self.lane,9 if self.lane in ('pump','meteora') else 0,Decimal('1'),int(now)-1,int(now)+120,'offline-value','e'*64)


def open_native(root,lane,epoch):
    folder=Path(root)/lane
    provider=MockProvider(lane)
    if lane=='pump':
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash,STRATEGY_ID
        book=PaperBook(folder/'paper.sqlite',run_id=epoch,lane=STRATEGY_ID,policy_hash=policy_hash(),initial=125_000_000_000)
        rows=[json.loads(row[0]) for row in book.db.execute('SELECT body FROM positions')]
    elif lane=='pons':
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        store=Store(folder/'paper.sqlite',max_records=8192)
        book=SelectivePaper(store,STRATEGY_NAMESPACE,125,delay=1,natural_policy_hash=POLICY_HASH)
        rows=book.positions()
    elif lane=='meteora':
        from meme_machine.lanes.meteora.dlmm_independent_accounting import PaperBook
        from meme_machine.lanes.meteora import runner
        book=PaperBook(folder/'paper.sqlite',run_id=epoch,policy_hash=runner.digest(runner.load_policy()),capital=1_000_000_000)
        with book.connect() as db:rows=[dict(p,id=i) for i,p in book._replay(db)['positions'].items()]
    else:
        from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger
        book=RamsesStrategyLedger(str(folder/'paper.sqlite'),paper_capital=125,quote_asset='fixture-quote')
        rows=[book.position(row[0]) for row in book.db.execute('SELECT id FROM ramses_strategy_position')]
    boundary=NativeBoundary(Path(root)/'portfolio.sqlite',lane,book,value_reader=provider.value)
    book.portfolio=boundary
    # Complete an interrupted shared acknowledgement before any mock discovery.
    boundary.recover()
    return book,rows,provider


def open_position(book,lane,epoch,now):
    native=issue(epoch+':fixture')
    if lane=='pump':
        book.reserve(native,6_250_000_000,now,dict(offline=True))
        book.transition(native,'filled',now,amount=6_000_000_000,tokens=1000,evidence=dict(execution=dict(gas=0)))
    elif lane=='pons':
        from meme_machine.lanes.pons.evidence import Stamp
        from meme_machine.lanes.pons.paper import Quote
        from meme_machine.lanes.pons.pons_selective_ledger import STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        book.reserve(native,market='fixture-market',amount=5,gas_budget=1,now=now-1,features=dict(asof=now-1,market='fixture-market',authority='frozen_policy_paper',qualification='qualified',policy_hash=POLICY_HASH,strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False))
        quote=Quote('fixture-market','buy',5,1000,1,0,Stamp(4663,1,'fixture-hash',now,now,'finalized','natural'))
        book.advance(native,now=now,action='entry',quote=quote)
    elif lane=='meteora':
        from meme_machine.lanes.meteora import dlmm,runner
        snapshot=json.loads(Path(__file__).with_name('offline-market.json').read_text())['meteora_snapshot']
        snapshot.update(market_time=now,available_time=now)
        entry=dlmm.validate(snapshot,now)
        features=dict(half_width_bins=4,lower=-4,upper=4,volume_rate_sol_lamports_per_second=1,fee_density=1)
        policy=runner.load_policy();position=runner._build_position(entry,features,policy)
        native=book.identity()
        book.append(native,'reserve',dict(amount=runner.CAPITAL+runner.ROUND_TRIP_NETWORK_COST,pool=entry['pool']))
        book.append(native,'entry',dict(capital=runner.CAPITAL,entry_cost=runner.ENTRY_NETWORK_COST,exit_cost=runner.EXIT_NETWORK_COST,
            entry_state=entry,features=features,policy=policy,position=position,mark=runner._mark(position)))
    else:
        from meme_machine.lanes.ramses.ramses_strategy import STRATEGY_DOMAIN,STRATEGY_VERSION,POLICY_HASH
        decision=dict(mode='active_wide_maker',qualified=True,allocation_authority=False,strategy_domain=STRATEGY_DOMAIN,strategy_version=STRATEGY_VERSION,policy_hash=POLICY_HASH,
            freeze=dict(proposal_hash='fixture',proposals=[dict(capital_employed=6)]))
        book.reserve(native,pool='fixture-pool',decision=decision,at=now)
        book.open(native,at=now)
    return native


def manage(book,lane,native,now):
    if lane=='pump':
        p=book._load(native)
        if p['status']=='reserved':book.transition(native,'filled',max(now,p['last_at']),amount=6_000_000_000,tokens=1000,evidence=dict(execution=dict(gas=0)))
        book.transition(native,'mark',max(now,p['last_at']),amount=7_000_000_000,evidence=dict(offline=True))
    elif lane=='pons':
        from meme_machine.lanes.pons.paper import Quote
        from meme_machine.lanes.pons.evidence import Stamp
        p=book._get(native)
        if p['status']=='reserved':
            when=max(now,p['due']);q=Quote(p['market'],'buy',p['amount'],1000,1,0,Stamp(4663,1,'fixture-hash',when,when,'finalized','natural'))
            book.advance(native,now=when,action='entry',quote=q);p=book._get(native)
        when=max(now,p['last_at']);q=Quote(p['market'],'sell',p['tokens'],8,1,0,Stamp(4663,1,'fixture-hash',when,when,'finalized','natural'))
        book.advance(native,now=when,action='mark',quote=q)
    elif lane=='meteora':
        # The real restoration replays frozen geometry and hysteresis. The mock
        # provider supplies no new verified segment, so it cannot advance them.
        from meme_machine.runtime.position_continuation import restore_meteora_strategy
        from meme_machine.lanes.meteora import runner
        restore_meteora_strategy(book,runner)
    else:
        book.checkpoint(native,action='monitor',detail=dict(action='hold',offline=True),at=now)


def close(book,lane):
    if lane=='pons':book.store.close()
    elif lane!='meteora':book.close()
