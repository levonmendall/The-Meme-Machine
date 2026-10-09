from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.runtime.survivor_commit import restore_risk
from meme_machine.runtime.source_artifacts import invalidate_sources
from tests.proven_efficiency_baseline import original_restore_risk


class RiskReplayReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'book'
        self.kwargs=dict(run_id='r',lane='survivor',policy_hash='p',initial=10000)
        self.book=PaperBook(self.path,**self.kwargs)
        self.book.reserve('r:p',100,1,{})
        self.book.transition('r:p','filled',2,amount=100,tokens=400)
    def tearDown(self):self.book.close();self.tmp.cleanup()

    def test_repeated_view_reuses_fold_but_verifies_every_monetary_replay(self):
        from meme_machine.runtime.survivor_commit import _fold_risk
        with patch('meme_machine.runtime.survivor_commit._fold_risk',wraps=_fold_risk) as fold,patch.object(self.book,'replay',wraps=self.book.replay) as verify:
            for _ in range(25):self.assertEqual(restore_risk(self.book,'r:p'),original_restore_risk(self.book,'r:p'))
            self.assertEqual(fold.call_count,1);self.assertEqual(verify.call_count,50)

    def test_returned_mutation_cannot_poison_verified_view(self):
        state=restore_risk(self.book,'r:p');state['original_basis']=1
        self.assertEqual(restore_risk(self.book,'r:p')['original_basis'],100)

    def test_each_mark_partial_scale_and_exit_matches_original(self):
        events=[('mark',dict(evidence=dict(risk_state=dict(original_basis=100,original_quantity=400,remaining_quantity=400,opened_at=2,high_water_bps=10000)))),
            ('partial_harvest',dict(amount=32,tokens=100)),
            ('scale_add',dict(amount=10,tokens=40,evidence=dict(request='r:p:scale:1'))),
            ('settled',dict(amount=90,tokens=340))]
        for at,(action,args) in enumerate(events,3):
            restore_risk(self.book,'r:p');self.book.transition('r:p',action,at,**args)
            self.assertEqual(restore_risk(self.book,'r:p'),original_restore_risk(self.book,'r:p'))

    def test_external_connection_projection_corruption_never_returns_a_cached_state(self):
        restore_risk(self.book,'r:p')
        external=sqlite3.connect(self.path)
        try:
            external.execute("UPDATE positions SET body=json_set(body,'$.tokens',999) WHERE id='r:p'");external.commit()
            with self.assertRaisesRegex(ValueError,'projection_differs'):restore_risk(self.book,'r:p')
            self.assertIsNone(self.book._risk_replay_cache)
            external.execute("UPDATE positions SET body=json_set(body,'$.tokens',400) WHERE id='r:p'");external.commit()
        finally:external.close()
        self.assertEqual(restore_risk(self.book,'r:p'),original_restore_risk(self.book,'r:p'))

    def test_local_recovery_source_changes_rollback_and_restart_invalidate(self):
        from meme_machine.runtime.survivor_commit import _fold_risk
        with patch('meme_machine.runtime.survivor_commit._fold_risk',wraps=_fold_risk) as fold:
            restore_risk(self.book,'r:p')
            self.book.checkpoint_runtime('r:p','recovery',dict(phase='pending'))
            restore_risk(self.book,'r:p')
            self.book.recovery_generation=2;restore_risk(self.book,'r:p')
            invalidate_sources();restore_risk(self.book,'r:p')
            with self.assertRaises(RuntimeError):
                with self.book.transaction():
                    self.book.db.execute("UPDATE runtime_state SET body='{}'");raise RuntimeError()
            restore_risk(self.book,'r:p');self.assertEqual(fold.call_count,5)
        self.book.close();self.book=PaperBook(self.path,**self.kwargs)
        self.assertFalse(hasattr(self.book,'_risk_replay_cache'))
        self.assertEqual(restore_risk(self.book,'r:p'),original_restore_risk(self.book,'r:p'))

    def test_position_ownership_change_does_not_share_state(self):
        restore_risk(self.book,'r:p');self.book.reserve('r:q',200,3,{})
        self.book.transition('r:q','filled',4,amount=200,tokens=800)
        self.assertEqual(restore_risk(self.book,'r:q')['original_basis'],200)
        self.assertEqual(restore_risk(self.book,'r:p')['original_basis'],100)
