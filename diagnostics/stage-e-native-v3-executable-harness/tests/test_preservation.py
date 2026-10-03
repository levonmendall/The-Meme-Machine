"""Finite filesystem/ledger tests. No native service, input frames or network."""
from pathlib import Path
import sys
import tempfile
import unittest
import os
import socket
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
from core import contract_file, read
from ledger import Ledger, fresh_campaign, trial_matrix
from preserve import persist, seal, verify_inventory, redundant_copy, abandoned_ipc, failure_copy
from run import _finalize_attempt, _finalize_campaign


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

    def abandoned(self, root):
        folder = root/'m1/d';folder.mkdir(parents=True)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(folder/'db.sock'));sock.close()
        (folder/'db').write_bytes(b'UNIT REGULAR DB EVIDENCE')
        (folder/'db-wal').write_bytes(b'UNIT REGULAR WAL EVIDENCE')
        return folder

    def test_abandoned_socket_cleanup_requires_confirmed_termination(self):
        folder = self.abandoned(self.root)
        with self.assertRaisesRegex(ValueError,'confirmed_process_termination'):abandoned_ipc(self.root,{})
        self.assertTrue((folder/'db.sock').exists())
        with self.assertRaises(ValueError):seal(self.root)

    def test_only_abandoned_IPC_is_removed_and_every_regular_byte_is_preserved(self):
        folder = self.abandoned(self.root)
        terminated = dict(trial_process_terminated=True,all_native_helpers_terminated=True)
        self.assertEqual(len(abandoned_ipc(self.root,terminated)),1)
        self.assertFalse((folder/'db.sock').exists())
        seal(self.root)
        self.assertEqual((folder/'db').read_bytes(),b'UNIT REGULAR DB EVIDENCE')
        self.assertEqual((folder/'db-wal').read_bytes(),b'UNIT REGULAR WAL EVIDENCE')
        self.assertFalse(read(self.root/'ABANDONED_IPC.json')['native_safety_credit'])

    def test_regular_file_named_db_socket_is_never_deleted(self):
        folder = self.root/'m1/d';folder.mkdir(parents=True);(folder/'db.sock').write_bytes(b'evidence')
        with self.assertRaisesRegex(ValueError,'not_socket'):
            abandoned_ipc(self.root,dict(trial_process_terminated=True,all_native_helpers_terminated=True))
        self.assertEqual((folder/'db.sock').read_bytes(),b'evidence')

    def test_failure_copy_keeps_all_regular_files_and_itemizes_specials(self):
        source = self.root/'source';source.mkdir();self.abandoned(source)
        os.mkfifo(source/'unit.fifo');(source/'link').symlink_to('/etc/os-release')
        (source/'regular').write_bytes(b'unit log')
        copied = failure_copy(source,self.root/'copy')
        receipt = read(self.root/'copy/FAILURE_COPY_RECEIPT.json')
        self.assertFalse(copied['acceptance_credit'])
        self.assertEqual({r['path'] for r in receipt['nonregular_artifacts_retained_locally']},
                         {'m1/d/db.sock','unit.fifo','link'})
        self.assertEqual((self.root/'copy/m1/d/db-wal').read_bytes(),b'UNIT REGULAR WAL EVIDENCE')
        self.assertTrue((source/'m1/d/db.sock').exists())

    def failure_attempt(self, *, special=False):
        ledger = self.ledger()
        ledger.append('STARTED',1,{})
        folder = ledger.path.parent/'t1';folder.mkdir()
        persist(folder/'UNIT_FAILURE.json',{'native_safety_credit':False})
        if special:os.mkfifo(folder/'unit.fifo')
        publication = self.root/'publication';publication.mkdir()
        declaration = dict(campaign=ledger.path.parent.name,paths={'durable_publication_root':str(publication)})
        return ledger,folder,declaration,publication

    def test_seal_exception_cannot_bypass_INVALID_or_regular_failure_publication(self):
        ledger,folder,d,pub = self.failure_attempt(special=True)
        result,error,terminal = _finalize_attempt(folder,d,1,valid=False,reason='unit failure',
                                                 declaration_sha256='unit',allocation={})
        self.assertIsNone(result);self.assertTrue(terminal);self.assertIn('raw_sealing_failure',error)
        self.assertEqual(ledger.events()[-1]['event'],'INVALID')
        self.assertIsNone(ledger.events()[-1]['details']['raw_inventory_sha256'])
        copy = pub/(d['campaign']+'-t1-failure')
        self.assertTrue((copy/'UNIT_FAILURE.json').is_file());self.assertTrue((copy/'SEAL_FAILURE.json').is_file())
        with self.assertRaises(ValueError):ledger.append('STARTED',2,{})

    def test_injected_sealing_IO_failure_still_records_and_publishes(self):
        ledger,folder,d,pub = self.failure_attempt()
        with patch('run.seal',side_effect=OSError('unit fsync failure')):
            _finalize_attempt(folder,d,1,valid=True,reason=None,declaration_sha256='unit',allocation={})
        self.assertEqual(ledger.events()[-1]['event'],'INVALID')
        self.assertTrue((pub/(d['campaign']+'-t1-failure')/'UNIT_FAILURE.json').exists())

    def test_socket_failure_is_cleaned_only_after_recorded_process_termination(self):
        ledger,folder,d,pub = self.failure_attempt();self.abandoned(folder)
        persist(folder/'PROCESS_TERMINATION.json',dict(trial_process_terminated=True,all_native_helpers_terminated=True))
        _finalize_attempt(folder,d,1,valid=False,reason='unit termination',declaration_sha256='unit',allocation={})
        self.assertEqual(ledger.events()[-1]['event'],'INVALID')
        self.assertFalse((folder/'m1/d/db.sock').exists())
        self.assertTrue((pub/(d['campaign']+'-t1')/'m1/d/db-wal').exists())

    def test_publication_error_does_not_erase_terminal_ledger(self):
        ledger,folder,d,pub = self.failure_attempt()
        with patch('run.redundant_copy',side_effect=OSError('unit publication failure')),\
             patch('run.failure_copy',side_effect=OSError('unit disk failure')):
            _,error,_ = _finalize_attempt(folder,d,1,valid=False,reason='unit failure',declaration_sha256='unit',allocation={})
        self.assertEqual(ledger.events()[-1]['event'],'INVALID')
        self.assertIn('failure_publication',error)
        self.assertTrue((folder/'UNIT_FAILURE.json').exists())

    def test_campaign_seal_failure_records_STOPPED_and_preserves_all_regular_bytes(self):
        ledger,folder,d,pub = self.failure_attempt(special=True)
        with self.assertRaisesRegex(ValueError,'campaign_preservation_failure'):
            _finalize_campaign(ledger.path.parent,d,ledger,'unit')
        self.assertEqual(ledger.events()[-1]['event'],'STOPPED')
        copy = pub/(d['campaign']+'-campaign-failure')
        self.assertTrue((copy/'LEDGER.jsonl').exists());self.assertTrue((copy/'t1/UNIT_FAILURE.json').exists())
