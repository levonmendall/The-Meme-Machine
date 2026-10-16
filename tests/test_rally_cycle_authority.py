"""Offline structural identity, funded-admission fences and bounded replay."""
import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime.rally_cycle import accumulate_outcomes,build_cycle,validate_cycle
from meme_machine.runtime.journal import digest
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.survivor_risk import new_regime


STRATEGY='pump-survivor'


def cycle(peak=10,*,generation=None,**updates):
    fields=dict(candidate='mint',venue='pumpswap',graduation=dict(at=0,identity='finalized-migration'),
        chain='offline-rally',pool='synthetic-canonical-pool',policy_hash=digest('synthetic-rally-policy'),
        input_version='synthetic-offline-v1',
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
        self.assertNotEqual(first['id'],cycle(chain='offline-other-chain')['id'])
        self.assertNotEqual(first['id'],cycle(pool='synthetic-other-pool')['id'])
        updated_policy=cycle(policy_hash=digest('synthetic-next-policy'),input_version='synthetic-offline-v2')
        self.assertEqual(first['id'],updated_policy['id'])
        self.assertNotEqual(first['certificate_hash'],updated_policy['certificate_hash'])
        forged=dict(first,reset_at=11)
        with self.assertRaisesRegex(ValueError,'certificate_invalid'):validate_cycle(forged)

    def test_unknown_evidence_or_incomplete_base_has_no_cycle_authority(self):
        for change in (dict(authoritative=False),dict(complete=False),dict(evidence_id=None),
                       dict(base_end=25),dict(reset_at=10),dict(breakout_at=40)):
            with self.subTest(change=change),self.assertRaises(ValueError):cycle(**change)

    def test_explicit_chain_pool_and_version_context_is_required_and_verified(self):
        for change in (dict(chain=None),dict(chain=True),dict(chain='unknown'),dict(pool=''),
                       dict(pool='unknown'),dict(policy_hash='unversioned'),dict(input_version='unversioned'),
                       dict(chain=4663,pool='not-a-v4-pool'),dict(chain='solana-mainnet',pool='not-a-solana-pool')):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'context_required'):
                cycle(**change)
        solana=cycle(chain='solana-mainnet',pool='1'*32)
        pons=cycle(chain=4663,pool='0x'+'ab'*32)
        self.assertEqual(validate_cycle(solana)['chain'],'solana-mainnet')
        self.assertEqual(validate_cycle(pons)['pool'],'0x'+'ab'*32)
        tampered=dict(pons,pool='unknown');tampered['certificate_hash']=digest({k:v for k,v in tampered.items() if k!='certificate_hash'})
        with self.assertRaisesRegex(ValueError,'certificate_invalid'):validate_cycle(tampered)

    def test_new_cycle_requires_whole_post_terminal_structure_and_decision_after_ack(self):
        old=regime(cycle());new=regime(cycle(3680))
        proof=dict(terminal_at=3680,global_ack_at=3719,obligations_clear=True)
        self.assertTrue(new_regime(old,new,settlement=proof))
        self.assertFalse(new_regime(old,new))
        self.assertFalse(new_regime(old,new,settlement=dict(proof,global_ack_at=3721)))
        # A verified breakout during terminal-publication lag remains useful;
        # only its execution decision must wait for the actual global ACK.
        delayed=regime(cycle(3680,decision_at=3730))
        self.assertTrue(new_regime(old,delayed,settlement=dict(proof,global_ack_at=3725)))
        self.assertFalse(new_regime(old,delayed,settlement=dict(proof,terminal_at=3721)))
        # A newly stamped breakout cannot relabel a pre-terminal peak/base as a
        # wholly independent post-settlement rally.
        self.assertFalse(new_regime(old,delayed,settlement=dict(proof,terminal_at=3681)))
        self.assertFalse(new_regime(old,new,settlement=dict(proof,obligations_clear=False)))
        self.assertFalse(new_regime(old,dict(new,at=3719),settlement=proof))
        self.assertFalse(new_regime(old,dict(old,at=3700,buyer_population=['other']),settlement=proof))

    def test_safe_young_independent_cycle_has_no_fixed_setup_spacing_execution_veto(self):
        old=regime(cycle());young=regime(cycle(200,decision_at=245))
        proof=dict(terminal_at=200,global_ack_at=241,obligations_clear=True)
        self.assertTrue(new_regime(old,young,settlement=proof))
        self.assertTrue(new_regime(old,young,settlement=proof,minimum_seconds=3600))
        self.assertLess(young['at']-old['at'],3600)

    def test_legacy_predicate_keeps_original_known_dimension_interpretation(self):
        old=dict(at=0,base_id='a',buyer_population=['one'])
        self.assertTrue(new_regime(old,dict(at=3600,base_id='b',buyer_population=['two'])))
        self.assertFalse(new_regime(old,dict(at=3599,base_id='b',buyer_population=['two'])))

    def _sleeve(self,path):
        return SleeveReservations(path,lane='pump',capital=1000,
            policies={'pump-current':'current-test',STRATEGY:'survivor-test'},cohort='rallies')

    def _observe(self,sleeve,c):
        return sleeve.observe('mint',strategy=STRATEGY,at=c['breakout_at'],state='qualified',
            evidence=dict(candidate=True),regime=regime(c))

    def _reserve(self,sleeve,identity,observed):
        return sleeve.reserve(identity,strategy=STRATEGY,amount=50,at=observed['at'],
            candidate='mint',generation=observed['generation'],regime=observed['regime'])

    def _readonly_legacy(self,path,identity):
        reader=object.__new__(SleeveReservations)
        reader.identity=identity;reader.lock=threading.RLock()
        from pathlib import Path
        reader.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        reader.db.execute('PRAGMA query_only=ON')
        return reader

    def _snapshot(self,sleeve,path,*,legacy=False):
        target=sqlite3.connect(path)
        sleeve.db.backup(target)
        if legacy:target.execute('DROP TABLE sleeve_rallies');target.commit()
        target.close()
        with open(path,'rb') as source:checksum=hashlib.file_digest(source,'sha256').hexdigest()
        return dict(snapshot_sha256=checksum,state_hash='preserved:'+checksum)

    def test_readonly_legacy_sleeve_replays_without_creating_rally_projection(self):
        with tempfile.TemporaryDirectory() as td:
            sleeve=self._sleeve(td+'/sleeve')
            sleeve.reserve('legacy-current',strategy='pump-current',amount=50,at=10)
            before=sleeve.reconcile();identity=sleeve.identity
            authority=self._snapshot(sleeve,td+'/old-schema',legacy=True)
            reader=self._readonly_legacy(td+'/old-schema',identity)
            try:
                self.assertEqual(reader.reconcile(),before)
                self.assertIsNone(reader.db.execute("SELECT 1 FROM sqlite_master WHERE name='sleeve_rallies'").fetchone())
                from meme_machine.operational.pause import native_positions
                self.assertEqual(native_positions(reader.db,'pump')[0]['id'],'legacy-current')
            finally:reader.db.close()
            with open(td+'/old-schema','rb') as source:
                self.assertEqual(hashlib.file_digest(source,'sha256').hexdigest(),authority['snapshot_sha256'])
            sleeve.close()

    def test_preserved_old_schema_prefix_compacts_without_new_source_table_or_money_change(self):
        with tempfile.TemporaryDirectory() as td:
            sleeve=self._sleeve(td+'/sleeve')
            sleeve.reserve('legacy-current',strategy='pump-current',amount=50,at=10)
            before=sleeve.reconcile()
            authority=self._snapshot(sleeve,td+'/old-schema',legacy=True)
            self.assertTrue(sleeve._compact_preserved(td+'/old-schema',authority))
            self.assertEqual(sleeve.reconcile(),before)
            self.assertEqual(sleeve._archive()['rallies'],{})
            self.assertEqual(sleeve.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],0)
            with sqlite3.connect('file:'+td+'/old-schema?mode=ro',uri=True) as source:
                self.assertIsNone(source.execute("SELECT 1 FROM sqlite_master WHERE name='sleeve_rallies'").fetchone())
            sleeve.close()

    def test_missing_rally_projection_with_journal_or_archived_cycles_is_corruption(self):
        for archived in (False,True):
            with self.subTest(archived=archived),tempfile.TemporaryDirectory() as td:
                sleeve=self._sleeve(td+'/sleeve');self._observe(sleeve,cycle())
                if archived:
                    authority=self._snapshot(sleeve,td+'/prefix')
                    sleeve._compact_preserved(td+'/prefix',authority)
                authority=self._snapshot(sleeve,td+'/missing-projection',legacy=True)
                reader=self._readonly_legacy(td+'/missing-projection',sleeve.identity)
                try:
                    with self.assertRaisesRegex(ValueError,'sleeve_rally_corruption'):reader.reconcile()
                finally:reader.db.close()
                before=sleeve.reconcile()
                with self.assertRaisesRegex(ValueError,'sleeve_rally_corruption'):
                    sleeve._compact_preserved(td+'/missing-projection',authority)
                self.assertEqual(sleeve.reconcile(),before)
                sleeve.close()

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
            second=self._observe(sleeve,cycle(200));self._reserve(sleeve,'second',second)
            shadow=second['regime']['setup_spacing_shadow']
            self.assertEqual(shadow,dict(prior_setup_at=50,current_setup_at=240,spacing=190,
                legacy3600pass=False,execution_veto=False))
            self.assertEqual(second['regime']['prior_cycle']['id'],observed['regime']['rally_cycle']['id'])
            report=sleeve.rally_report()
            self.assertEqual(report['rows'][0]['setup_spacing_shadow'],shadow)
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

    def test_modern_native_admission_rejects_other_policy_certificate_before_funding(self):
        from meme_machine.lanes.pump.pumpswap_survivor import STRATEGY_ID
        from meme_machine.runtime.directional_sleeve import policies
        with tempfile.TemporaryDirectory() as td:
            sleeve=SleeveReservations(td+'/sleeve',lane='pump',capital=1000,
                policies=policies('pump'),cohort='rallies')
            c=cycle(policy_hash=digest('other-policy'))
            observed=sleeve.observe('mint',strategy=STRATEGY_ID,at=c['breakout_at'],state='qualified',
                evidence=dict(candidate=True),regime=regime(c))
            with self.assertRaisesRegex(ValueError,'rally_cycle_policy_mismatch'):
                sleeve.reserve('wrong-policy',strategy=STRATEGY_ID,amount=50,at=observed['at'],
                    candidate='mint',generation=observed['generation'],regime=observed['regime'])
            self.assertIsNone(sleeve.get('wrong-policy'))
            sleeve.close()
