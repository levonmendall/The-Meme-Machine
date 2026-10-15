"""Native preserved-prefix replay/rollback with isolated epoch fixtures."""
import unittest
from tests.native_inline import run_native

COMMON = r'''
from contextlib import closing
from copy import deepcopy
import os,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime.lifecycle_identity import issue
from meme_machine.runtime.preserved_checkpoint import snapshot
os.environ['MM_PAPER_EPOCH']='offline-native-prefix'
class FailAfterArchiveInsert:
    def __init__(self,db):self.db=db
    def __getattr__(self,name):return getattr(self.db,name)
    def execute(self,sql,*args):
        result=self.db.execute(sql,*args)
        if sql.startswith('INSERT OR REPLACE INTO') and 'archive' in sql:
            raise SystemExit('after_archive_insert')
        return result
'''

RAMSES = COMMON + r'''
from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger
from meme_machine.lanes.ramses.ramses_strategy import STRATEGY_DOMAIN
from meme_machine.runtime.ramses_archive import compact,anchor
from tests.lanes.ramses.test_ramses_capital_replay import decision
with tempfile.TemporaryDirectory() as td:
    folder=Path(td)/'robinhood-ramses-extended-market.sqlite.campaign';folder.mkdir()
    path=folder/('0x'+'12'*20+'.sqlite')
    args=dict(paper_capital=1000,quote_asset='fixture-usdg')
    book=RamsesStrategyLedger(str(path),**args)
    terminal=issue('terminal');active=issue('active');legacy='old-unscoped-terminal'
    for identity in (terminal,legacy):
        book.reserve(identity,pool='pool-'+identity,decision=decision(100),at=10)
        book.open(identity,at=11)
        book.checkpoint(identity,action='monitor',detail={'action':'hold'},at=12)
        book.settle(identity,pnl={'strategy_domain':STRATEGY_DOMAIN,'net_result_quote':30,'unresolved_inventory':None},at=13)
    book.reserve(active,pool='active-pool',decision=decision(100),at=14);book.open(active,at=15)
    before=book.reconcile();active_before=book.position(active);legacy_before=book.position(legacy)
    rows_before=list(book.db.execute('SELECT * FROM ramses_strategy_journal ORDER BY seq'))
    with snapshot(path,name='ramses/native',lane='ramses') as preserved:
        source,authority=preserved
        if INTERRUPT:
            connection=book.db;book.db=FailAfterArchiveInsert(connection)
            try:
                try:compact(book,source,authority)
                except SystemExit as error:assert str(error)=='after_archive_insert'
                else:raise AssertionError('missing archive interruption')
            finally:book.db=connection
            assert not book.db.in_transaction and anchor(book.db) is None
            assert list(book.db.execute('SELECT * FROM ramses_strategy_journal ORDER BY seq'))==rows_before
            assert book.reconcile()==before
        else:
            try:compact(book,source,dict(authority,snapshot_sha256='0'*64))
            except ValueError as error:assert str(error)=='ramses_terminal_snapshot_identity'
            else:raise AssertionError('corrupt snapshot accepted')
            assert list(book.db.execute('SELECT * FROM ramses_strategy_journal ORDER BY seq'))==rows_before
        assert compact(book,source,authority) is True
        assert compact(book,source,authority) is False
    proof=anchor(book.db);assert proof['folded']['positions']==1 and proof['folded']['realized']==30
    assert book.db.execute('SELECT COUNT(*) FROM ramses_strategy_position WHERE id=?',(terminal,)).fetchone()[0]==0
    assert book.position(active)==active_before and book.position(legacy)==legacy_before
    assert book.reconcile()==before
    try:book.reserve(terminal,pool='resurrection',decision=decision(100),at=16)
    except ValueError as error:assert 'archived_lifecycle_replay' in str(error)
    else:raise AssertionError('retired native identity resurrected')
    book.close()
    # This exact deployed path activates the constructor's real local snapshot
    # and compaction path, without an external campaign/certification controller.
    reopened=RamsesStrategyLedger(str(path),**args)
    assert reopened.reconcile()==before and reopened.position(active)==active_before
    assert reopened.position(legacy)==legacy_before
    assert reopened.db.execute('PRAGMA quick_check').fetchone()==('ok',)
    reopened.close()
'''

METEORA = COMMON + r'''
from meme_machine.lanes.meteora import runner as strategy
from meme_machine.lanes.meteora.dlmm_independent_accounting import PaperBook
from meme_machine.runtime.meteora_archive import compact,anchor
from meme_machine.runtime.position_continuation import restore_meteora_strategy
from tests.lanes.meteora.test_dlmm_independent_accounting import DurableIndependentAccounting
case=DurableIndependentAccounting();case.setUp()
try:
    terminal=case.run_lifecycle()['lifecycle_id']
    def no_evidence(*args):return dict(verified=False,reason='fixture_unavailable'),None,None,None,None
    with patch.object(strategy,'_rotate',side_effect=lambda a,*args:a),patch.object(strategy,'_observe_window',side_effect=no_evidence):
        active_result=strategy._lifecycle(None,case.entry['pool'],case.entry,case.features,case.policy,None,[],book=case.book)[0]
    active=active_result['lifecycle_id'];book=case.book
    callbacks=(strategy._build_position,strategy._advance_position,strategy._mark)
    before=book.reconcile();economic=book.replay_economics(*callbacks)
    active_before=restore_meteora_strategy(book,strategy)
    with closing(book.connect()) as db:rows_before=list(db.execute('SELECT * FROM events ORDER BY seq'))
    with snapshot(case.path,name='meteora/native',lane='meteora') as preserved:
        source,authority=preserved
        if INTERRUPT:
            connect=book.connect
            with patch.object(book,'connect',side_effect=lambda:FailAfterArchiveInsert(connect())):
                try:compact(book,source,authority,callbacks)
                except SystemExit as error:assert str(error)=='after_archive_insert'
                else:raise AssertionError('missing archive interruption')
            with closing(book.connect()) as db:
                assert anchor(db,book.genesis) is None
                assert list(db.execute('SELECT * FROM events ORDER BY seq'))==rows_before
                assert db.execute('PRAGMA quick_check').fetchone()==('ok',)
            assert book.reconcile()==before
        else:
            try:compact(book,source,dict(authority,snapshot_sha256='0'*64),callbacks)
            except ValueError as error:assert str(error)=='meteora_archive_snapshot_identity'
            else:raise AssertionError('corrupt snapshot accepted')
            with closing(book.connect()) as db:assert list(db.execute('SELECT * FROM events ORDER BY seq'))==rows_before
        assert compact(book,source,authority,callbacks) is True
        assert compact(book,source,authority,callbacks) is False
    assert book.reconcile()==before and book.replay_economics(*callbacks)==economic
    assert restore_meteora_strategy(book,strategy)==active_before
    with closing(book.connect()) as db:
        state=book._replay(db);proof=anchor(db,book.genesis)
        assert terminal not in state['positions'] and active in state['positions']
        assert proof['folded']['settled']==1
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
    try:book.append(terminal,'reserve',dict(amount=1))
    except ValueError as error:assert 'archived_lifecycle_replay' in str(error)
    else:raise AssertionError('retired native identity resurrected')
    reopened=PaperBook(case.path,run_id=book.run_id,policy_hash=book.policy_hash,capital=book.genesis['capital'],economic_replay=callbacks)
    assert reopened.reconcile()==before and reopened.replay_economics(*callbacks)==economic
    assert restore_meteora_strategy(reopened,strategy)==active_before
finally:case.doCleanups()
'''

class NativeTerminalPrefixTests(unittest.TestCase):
    def check(self,script,*,interrupt):
        result=run_native(script.replace('if INTERRUPT:',f'if {interrupt!r}:'),timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_ramses_terminal_fold_keeps_active_and_legacy_economics_on_restart(self):
        self.check(RAMSES,interrupt=False)

    def test_ramses_interrupted_fold_rolls_back_and_retries_once(self):
        self.check(RAMSES,interrupt=True)

    def test_meteora_terminal_fold_keeps_verified_active_tape_on_restart(self):
        self.check(METEORA,interrupt=False)

    def test_meteora_interrupted_fold_rolls_back_and_retries_once(self):
        self.check(METEORA,interrupt=True)
