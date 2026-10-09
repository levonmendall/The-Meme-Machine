from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.source_artifacts import ArtifactRegistry,REGISTRY,freeze,invalidate_sources
from meme_machine.lanes.pons.abi import CompiledABI,decode_event
from meme_machine.lanes.pons.identity import load,metadata
from meme_machine.lanes.pons.pons import curve_abi,TEMPLATE
from meme_machine.lanes.pons import BoundaryError


class ArtifactTests(unittest.TestCase):
    def tearDown(self):invalidate_sources()

    def test_frozen_capture_events_match_original_decoding_without_reparsing(self):
        capture=json.loads((Path(__file__).parent/'lanes/pons/fixtures/protocol_capture_35370277849.json').read_text())
        old=json.loads(TEMPLATE.read_text())['abi'];invalidate_sources()
        selected={c['address'] for c in capture['lanes']['pons']['curves']}
        events=[e for e in capture['lanes']['pons']['unverified_curve_activity'] if e['address'] in selected]
        before=REGISTRY.stats().get('parses',0)
        for e in events:
            self.assertEqual(decode_event(curve_abi(),e),decode_event(old,e))
        self.assertGreater(len(events),1)
        self.assertEqual(REGISTRY.stats()['parses']-before,2)  # Template + its verified compiler input.

    def test_cached_metadata_is_immutable_and_compatibility_copies_are_independent(self):
        first=metadata('pons_v2_factory');second=metadata('pons_v2_factory')
        self.assertIs(first,second)
        with self.assertRaises(TypeError):first['address']='bad'
        with self.assertRaises(TypeError):first['abi'][0]['name']='bad'
        with self.assertRaises(TypeError):first['abi'].dispatch['bad']=()
        copy=load('pons_v2_factory');copy['address']='bad';copy['abi'][0]['type']='bad'
        self.assertNotEqual(first['address'],'bad');self.assertNotEqual(first['abi'][0]['type'],'bad')

    def test_replacement_missing_invalid_and_generation_changes_never_serve_stale(self):
        registry=ArtifactRegistry(max_entries=2,max_bytes=10000)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source';p.write_text('{"value":1}')
            self.assertEqual(registry.get(p)['value'],1)
            p.write_text('{"value":2}')
            self.assertEqual(registry.get(p)['value'],2)
            p.write_text('{')
            with self.assertRaises(ValueError):registry.get(p)
            self.assertEqual(registry.stats()['entries'],0)
            p.write_text('{"value":3}');registry.get(p);p.unlink()
            with self.assertRaises(FileNotFoundError):registry.get(p)
            self.assertEqual(registry.stats()['entries'],0)
            p.write_text('{"value":4}');a=registry.get(p,generation=1);b=registry.get(p,generation=2)
            self.assertIsNot(a,b);registry.invalidate();self.assertIsNot(b,registry.get(p,generation=2))

    def test_size_count_and_validation_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);registry=ArtifactRegistry(max_entries=2,max_bytes=10000,max_artifact_bytes=200)
            for i in range(5):
                p=root/str(i);p.write_text(json.dumps(dict(value=i)));registry.get(p)
            self.assertEqual(registry.stats()['entries'],2)
            self.assertLessEqual(len(registry.watches),2)
            self.assertEqual(registry.stats().get('evictions',0)+registry.stats().get('watch_evictions',0),3)
            p=root/'bad';p.write_text('"'+'x'*200+'"')
            with self.assertRaisesRegex(ValueError,'size_bound'):registry.get(p)
            p.write_text('{}')
            with self.assertRaises(ValueError):registry.get(p,validate=lambda v:(_ for _ in ()).throw(ValueError()))

    def test_changed_evicted_artifact_watches_remain_bounded_and_fallback_reloads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);registry=ArtifactRegistry(max_entries=2,max_bytes=10000)
            for i in range(12):
                p=root/str(i);p.write_text('{"v":1}');registry.get(p)
                p.write_text('{"v":2}')
            self.assertLessEqual(len(registry.watches),2)
            self.assertEqual(registry.get(root/'0')['v'],2)
            portable=ArtifactRegistry(max_entries=2,max_bytes=10000)
            portable_fd=portable.watch_fd;portable.watch_fd=-1
            if portable_fd>=0:
                import os
                os.close(portable_fd)
            p=root/'0';self.assertEqual(portable.get(p)['v'],2)
            p.write_text('{"v":3}');self.assertEqual(portable.get(p)['v'],3)

    def test_duplicate_anonymous_dynamic_and_malformed_topics_keep_strict_refusal(self):
        abi=load('pons_v2_factory')['abi'];compiled=CompiledABI(freeze(abi))
        event=dict(topics=['0x'+'00'*32],data='0x')
        for specs in (abi,compiled):
            with self.assertRaisesRegex(BoundaryError,'unsupported_event_signature'):decode_event(specs,event)
        spec=next(a for a in abi if a['type']=='event' and not a.get('anonymous'))
        from meme_machine.lanes.pons.abi import topic,signature
        event['topics']=[topic(signature(spec))]
        for specs in ([spec,spec],CompiledABI(freeze([spec,spec]))):
            with self.assertRaisesRegex(BoundaryError,'unsupported_event_signature'):decode_event(specs,event)
        for specs in (abi,compiled):
            with self.assertRaisesRegex(BoundaryError,'event_topic_count'):decode_event(specs,event)

    def test_curve_missing_or_bad_template_refuses_after_a_successful_load(self):
        curve_abi()
        with tempfile.TemporaryDirectory() as td:
            missing=Path(td)/'missing'
            with patch('meme_machine.lanes.pons.pons.TEMPLATE',missing):
                with self.assertRaisesRegex(BoundaryError,'source_artifact_unavailable'):curve_abi()
            missing.write_text('{}')
            with patch('meme_machine.lanes.pons.pons.TEMPLATE',missing):
                with self.assertRaises(BoundaryError):curve_abi()
