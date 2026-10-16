"""Offline structural identity, funded-admission fences and bounded replay."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.rally_cycle import accumulate_outcomes,build_cycle,validate_cycle
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.survivor_risk import new_regime


STRATEGY='pump-survivor'


def cycle(peak=10,*,generation=None,**updates):
    fields=dict(candidate='mint',venue='pumpswap',graduation=dict(at=0,identity='finalized-migration'),
        peak_at=peak,reset_at=peak+10,base_start=peak+10,base_end=peak+30,
        breakout_at=peak+40,decision_at=peak+40,evidence_id='authenticated-history-'+str(peak),
        authoritative=True,complete=True,minimum_base_seconds=10,canonical_generation=generation)
    fields.update(updates)
    return build_cycle(**fields)


def regime(c):return dict(at=c['breakout_at'],rally_cycle=c,buyer_population=['fresh'])


class RallyAuthority(unittest.TestCase):
    def test_fixed_lifecycle_outcome_buckets_keep_unknown_basis_unknown(self):
        first=dict(terminal_count=1,realized_pnl=5,original_basis=50,missing_original_basis=0)
        unknown=dict(terminal_count=1,realized_pnl=-2,original_basis=0,missing_original_basis=1)
        result=accumulate_outcomes({},dict(first=first,second=first,third=first,later=unknown))
        self.assertEqual(set(result),{'first','second','third','later'})
        self.assertEqual(result['third']['after_cost_return_bps'],1000)
        self.assertIsNone(result['later']['after_cost_return_bps'])
        updated=accumulate_outcomes(result,dict(later=first))
        self.assertEqual(updated['later']['terminal_count'],2)
        self.assertEqual(updated['later']['realized_pnl'],3)
        self.assertIsNone(updated['later']['after_cost_return_bps'])

    def test_structure_identity_does_not_use_deeper_reset_or_moving_base_and_decision(self):
        first=cycle()
        later=cycle(reset_at=25,base_start=25,base_end=45,breakout_at=60,decision_at=61,
            evidence_id='newer-authenticated-history')
        self.assertEqual(first['id'],later['id'])
        self.assertNotEqual(first['certificate_hash'],later['certificate_hash'])
        self.assertNotEqual(first['id'],cycle(100)['id'])
        forged=dict(first,reset_at=11)
        with self.assertRaisesRegex(ValueError,'certificate_invalid'):validate_cycle(forged)

    def test_unknown_evidence_or_incomplete_base_has_no_cycle_authority(self):
        for change in (dict(authoritative=False),dict(complete=False),dict(evidence_id=None),
                       dict(base_end=25),dict(reset_at=10),dict(breakout_at=40)):
            with self.subTest(change=change),self.assertRaises(ValueError):cycle(**change)

    def test_new_cycle_requires_setup_spacing_and_post_ack_breakout_without_extra_hour(self):
        old=regime(cycle());new=regime(cycle(3660))
        proof=dict(terminal_at=3680,global_ack_at=3699,obligations_clear=True)
        self.assertTrue(new_regime(old,new,settlement=proof))
        self.assertFalse(new_regime(old,new))
        self.assertFalse(new_regime(old,new,settlement=dict(proof,global_ack_at=3701)))
        # A verified breakout during terminal-publication lag remains useful;
        # only its execution decision must wait for the actual global ACK.
        delayed=regime(cycle(3660,decision_at=3710))
        self.assertTrue(new_regime(old,delayed,settlement=dict(proof,global_ack_at=3705)))
        self.assertFalse(new_regime(old,delayed,settlement=dict(proof,terminal_at=3701)))
        self.assertFalse(new_regime(old,new,settlement=dict(proof,obligations_clear=False)))
        self.assertFalse(new_regime(old,dict(new,at=3649),settlement=proof))
        self.assertFalse(new_regime(old,dict(old,at=3700,buyer_population=['other']),settlement=proof))

    def test_legacy_predicate_keeps_original_known_dimension_interpretation(self):
        old=dict(at=0,base_id='a',buyer_population=['one'])
        self.assertTrue(new_regime(old,dict(at=3600,base_id='b',buyer_population=['two'])))

    def _sleeve(self,path):
        return SleeveReservations(path,lane='pump',capital=1000,
            policies={'pump-current':'current-test',STRATEGY:'survivor-test'},cohort='rallies')

    def _observe(self,sleeve,c):
        return sleeve.observe('mint',strategy=STRATEGY,at=c['breakout_at'],state='qualified',
            evidence=dict(candidate=True),regime=regime(c))

    def _reserve(self,sleeve,identity,observed):
        return sleeve.reserve(identity,strategy=STRATEGY,amount=50,at=observed['at'],
            candidate='mint',generation=observed['generation'],regime=observed['regime'])

    def test_cancel_retry_recovery_trade_and_prefix_compaction_preserve_consumption(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=False):
            sleeve=self._sleeve(td+'/sleeve')
            proof=dict(terminal_at=100,global_ack_at=101,obligations_clear=True)
            sleeve.reentry_verified=lambda identity:proof
            observed=self._observe(sleeve,cycle())
            self._reserve(sleeve,'cancelled',observed)
            sleeve.release('cancelled',pnl=0,at=60,terminal_hash='verified-cancel',native_verified=True,cancelled=True)
            self._reserve(sleeve,'first',observed)
            # Recovery after a native fill/global ACK, before commit_fence's
            # local post-yield update, must mark this cycle consumed exactly once.
            sleeve.acknowledge_native('first',basis=50,pnl=0,at=70,native_hash='native-entry',
                native_verified=True,entry_fill_at=65,entry_basis=50)
            sleeve.acknowledge_native('first',basis=50,pnl=0,at=70,native_hash='native-entry',
                native_verified=True,entry_fill_at=65,entry_basis=50)
            sleeve.release('first',pnl=5,at=100,terminal_hash='verified-terminal',native_verified=True)
            stats=sleeve.rally('mint',strategy=STRATEGY)
            self.assertEqual((stats['traded_count'],stats['cancelled_count']),(1,1))
            self.assertEqual(stats['last_traded']['after_cost_return_bps'],1000)
            self.assertEqual(stats['last_traded']['entry_fill_at'],65)
            self.assertEqual(stats['outcomes']['first']['terminal_count'],1)
            self.assertEqual(stats['outcomes']['first']['realized_pnl'],5)
            self.assertEqual(len(stats['completed']),1)
            later=self._observe(sleeve,cycle(base_end=45,breakout_at=60,decision_at=60))
            self.assertEqual(later['regime']['rally_cycle']['breakout_at'],50)
            with self.assertRaisesRegex(ValueError,'same_survivor_regime'):
                self._reserve(sleeve,'duplicate',later)
            snapshot=td+'/snapshot'
            target=sqlite3.connect(snapshot);sleeve.db.backup(target);target.close()
            with open(snapshot,'rb') as source:checksum=hashlib.file_digest(source,'sha256').hexdigest()
            sleeve._compact_preserved(snapshot,dict(snapshot_sha256=checksum,state_hash='preserved'))
            self.assertEqual(sleeve.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],0)
            sleeve.close();sleeve=self._sleeve(td+'/sleeve');sleeve.reentry_verified=lambda identity:proof
            self.assertEqual(sleeve.rally('mint',strategy=STRATEGY)['traded_count'],1)
            second=self._observe(sleeve,cycle(3660));self._reserve(sleeve,'second',second)
            with sleeve.commit_fence('second'):pass
            self.assertEqual(sleeve.rally('mint',strategy=STRATEGY)['traded_count'],2)
            sleeve.close()

    def test_canonical_reorg_supersedes_certificate_but_cannot_mint_new_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            sleeve=self._sleeve(td+'/sleeve')
            before=self._observe(sleeve,cycle(generation='canonical-0'))
            self._reserve(sleeve,'old-fork',before)
            after=self._observe(sleeve,cycle(generation='canonical-1'))
            self.assertEqual(before['regime']['rally_cycle']['id'],after['regime']['rally_cycle']['id'])
            self.assertGreater(after['generation'],before['generation'])
            with self.assertRaisesRegex(ValueError,'superseded_commit'):
                with sleeve.commit_fence('old-fork'):pass
            sleeve.close()
