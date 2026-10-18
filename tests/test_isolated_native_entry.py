"""Bounded receiving contract; no live parent producer or provider workload."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from meme_machine.operational.isolated_native_entry import ParentSizingReader,IsolatedEntryBlocked
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests.test_isolated_native_resources import authenticated,receipt


class IsolatedNativeEntryTests(unittest.TestCase):
    def setUp(self):
        self.read,self.write=os.pipe()
        self.addCleanup(os.close,self.write)
        self.stopped=threading.Event()
        self.reader=ParentSizingReader(self.read,session='s'*43,
            source_commit='a'*40,source_tree='b'*40,stopped=self.stopped.is_set)
        self.addCleanup(self.reader.close)

    def send(self,value):
        packet=dict(schema='protected-parent-native-sizing-v1',session='s'*43,facts=value)
        os.write(self.write,json.dumps(packet,separators=(',',':')).encode()+b'\n')

    def test_exact_parent_pipe_facts_bind_session_source_and_remain_readonly(self):
        self.send(receipt())
        facts=self.reader.receive()
        self.assertEqual(facts.value(),receipt())
        self.assertGreater(facts.basis('pump',500,at=1000)['target'],0)
        self.assertFalse(facts.basis('pump',500,at=1000)['allocation_authority'])
        with self.assertRaises(AttributeError):facts.receipt_hash='forged'

    def test_refresh_uses_existing_capability_epoch_sequence_and_usd_expiry_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[1001]
            resources=IsolatedNativeResources(Path(directory)/'owned',
                sizing_facts=authenticated(receipt()),clock=lambda:now[0])
            try:
                self.send(receipt(1001))
                self.reader.apply_next(resources)
                self.assertEqual(resources.facts.value()['observed_at'],1001)
                bad=receipt(1002);bad['epoch_reference']='different-parent-epoch'
                self.send(bad)
                with self.assertRaisesRegex(ValueError,'binding_changed'):
                    self.reader.apply_next(resources)
                self.assertFalse(list(resources.root.glob('*.sqlite*')))
            finally:resources.close()

    def test_foreign_source_or_session_refused_without_resource_open(self):
        value=receipt();value['source_commit']='c'*40
        self.send(value)
        with self.assertRaisesRegex(IsolatedEntryBlocked,'source_changed'):
            self.reader.receive()
        os.write(self.write,json.dumps(dict(schema='protected-parent-native-sizing-v1',
            session='foreign',facts=receipt())).encode()+b'\n')
        with self.assertRaisesRegex(IsolatedEntryBlocked,'envelope'):
            self.reader.receive()

    def test_regular_file_and_write_end_cannot_become_parent_fact_capability(self):
        with tempfile.TemporaryFile() as regular:
            with self.assertRaisesRegex(IsolatedEntryBlocked,'pipe_required'):
                ParentSizingReader(regular.fileno(),session='s'*43,source_commit='a'*40,
                    source_tree='b'*40,stopped=lambda:False)
        with self.assertRaisesRegex(IsolatedEntryBlocked,'pipe_required'):
            ParentSizingReader(self.write,session='s'*43,source_commit='a'*40,
                source_tree='b'*40,stopped=lambda:False)

    def test_no_parent_packet_has_one_bounded_deadline(self):
        with self.assertRaisesRegex(IsolatedEntryBlocked,'unavailable'):
            self.reader.receive(seconds=.02)

    def test_cancel_refuses_even_an_already_buffered_parent_message(self):
        self.send(receipt());self.send(receipt())
        self.reader.receive()
        self.stopped.set()
        with self.assertRaisesRegex(IsolatedEntryBlocked,'stopped'):
            self.reader.receive()

    def test_failure_projection_keeps_fixed_caller_and_known_code_without_paths_or_messages(self):
        from meme_machine.operational.isolated_native_entry import _failure_details
        from meme_machine.operational.isolated_native_source import ContainedNativeFailure
        source=('def _require():\n    raise ValueError("secret arbitrary provider body")\n'
            'def caller():\n    _require()\n')
        scope={'__name__':'meme_machine.operational.source_ports'}
        exec(compile(source,'/private/secret/provider-url.py','exec'),scope)
        try:scope['caller']()
        except ValueError as error:value=_failure_details(error,'native_lifecycle')
        self.assertEqual(value,dict(failure_code='isolated_native_child_failed',failure_type='ValueError',
            failure_stage='native_lifecycle',failure_site=dict(module=scope['__name__'],line=4)))
        for error in (ContainedNativeFailure('isolated_native_consumer_ended'),
                ContainedNativeFailure('secret arbitrary provider body'),
                ValueError('isolated_native_consumer_ended'),PermissionError(1,'secret arbitrary provider body')):
            row=_failure_details(error,'native_lifecycle')
            self.assertNotIn('secret',json.dumps(row))
            self.assertEqual('boundary_code' in row,type(error) is ContainedNativeFailure
                and error.args==('isolated_native_consumer_ended',))
        self.assertEqual(_failure_details(PermissionError(1,'private'),'native_lifecycle')['error_number'],1)


if __name__=='__main__':
    unittest.main()
