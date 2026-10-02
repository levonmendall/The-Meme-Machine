"""Finite filesystem/ledger tests. No native service, input frames or network."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
from core import contract_file
from ledger import Ledger, fresh_campaign, trial_matrix
from preserve import persist, seal, verify_inventory, redundant_copy


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_exclusive_receipts_cannot_overwrite(self):
        path=self.root/'receipt.json';persist(path,{'a':1})
        with self.assertRaises(FileExistsError):persist(path,{'a':2})

    def test_inventory_detects_byte_change(self):
        persist(self.root/'data.json',{'a':1});seal(self.root)
        self.assertEqual(len(verify_inventory(self.root)['artifacts']),1)
        (self.root/'data.json').write_text('changed')
        with self.assertRaises(ValueError):verify_inventory(self.root)

    def test_inventory_detects_extra_file(self):
        seal(self.root);(self.root/'extra').write_bytes(b'x')
        with self.assertRaises(ValueError):verify_inventory(self.root)

    def test_symlink_refused(self):
        (self.root/'link').symlink_to('/etc/os-release')
        with self.assertRaises(ValueError):seal(self.root)

    def test_durable_copy_readback_retains_original(self):
        source=self.root/'source';source.mkdir();persist(source/'receipt.json',{'fixture':True});seal(source)
        copied=redundant_copy(source,self.root/'copy')
        self.assertTrue(copied['local_copy_retained'])
        self.assertTrue((source/'receipt.json').exists())
        with self.assertRaises(ValueError):redundant_copy(source,self.root/'copy')

    def test_campaign_authority_and_ledger_are_copied_together(self):
        source=self.root/'campaign';source.mkdir()
        persist(source/'UNIT_AUTHORITY_NOT_AUTHORIZED.json',{'execution_authorized':False})
        persist(source/'UNIT_LEDGER.json',{'source_frames_released':0})
        seal(source,name='CAMPAIGN_INVENTORY.json')
        redundant_copy(source,self.root/'campaign-copy',name='CAMPAIGN_INVENTORY.json')
        self.assertEqual(len(verify_inventory(self.root/'campaign-copy',name='CAMPAIGN_INVENTORY.json')['artifacts']),2)

    def ledger(self, kind='B'):
        return Ledger.create(self.root,kind,'a'*64,fresh_campaign(kind))

    def test_trial_consumed_before_completion_no_retry(self):
        ledger=self.ledger();ledger.append('STARTED',1,{})
        with self.assertRaises(ValueError):ledger.append('STARTED',1,{})
        with self.assertRaises(ValueError):ledger.append('STARTED',2,{})

    def test_failure_terminal_old_unused_not_reusable(self):
        ledger=self.ledger();ledger.append('STARTED',1,{});ledger.append('INVALID',1,{})
        with self.assertRaises(ValueError):ledger.append('STARTED',2,{})

    def test_exact_sequential_six_slots(self):
        ledger=self.ledger()
        for i in range(1,7):
            ledger.append('STARTED',i,{});ledger.append('COMPLETE_VALID',i,{})
        with self.assertRaises(ValueError):ledger.append('STARTED',7,{})
        self.assertEqual(len(ledger.events()),13)

    def test_campaign_namespace_cannot_be_created_twice(self):
        campaign=fresh_campaign('A');Ledger.create(self.root,'A','a'*64,campaign)
        with self.assertRaises(FileExistsError):Ledger.create(self.root,'A','a'*64,campaign)

    def test_torn_ledger_fails_closed(self):
        ledger=self.ledger();ledger.path.write_bytes(ledger.path.read_bytes()[:-1])
        with self.assertRaises(ValueError):ledger.events()

    def test_changed_ledger_hash_chain_fails(self):
        ledger=self.ledger();ledger.path.write_bytes(ledger.path.read_bytes().replace(b'CREATED',b'STOPPED'))
        with self.assertRaises(ValueError):ledger.events()

    def test_boolean_slot_cannot_be_integer_one(self):
        ledger=self.ledger()
        with self.assertRaises(ValueError):ledger.append('STARTED',True,{})

    def test_valid_hash_chain_cannot_hide_invalid_event_order(self):
        from core import canonical,read,sha
        ledger=self.ledger();ledger.append('STARTED',1,{})
        rows=ledger.events();rows[1]['sequence']=2
        raw=dict(rows[1]);raw.pop('sha256');rows[1]['sha256']=sha(canonical(raw))
        ledger.path.write_bytes(b''.join(canonical(r)+b'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'ledger_start_order'):ledger.events()

    def test_v2_identity_refused_and_history_unchanged(self):
        seal_=contract_file('historical_observer_seal.json')
        self.assertEqual(seal_['outcome'],'OBSERVER_V2: INVALID_PAIR')
        self.assertEqual(seal_['unused_slot_sequences_forbidden'],[2,3,4,5,6])
        for name in seal_['all_old_trial_ids_forbidden']:
            with self.assertRaises(ValueError):trial_matrix(name,'B')
        self.assertIsNone(seal_['denominator_ns'])
        self.assertIsNone(seal_['numerator_ns'])
