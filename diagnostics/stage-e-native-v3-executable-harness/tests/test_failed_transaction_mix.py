"""Fixed-tape semantics and counterfactuals; no feeder or native service."""
import ast
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'harness'))
import tape
from core import MAGIC, canonical, file_sha, workload


class FailedTransactionMixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'unit.tape'
        self.path.write_bytes(MAGIC+b'UNIT ONLY')
        self.path.chmod(0o444)
        self.inventory = self.root/'FRAMES.json'
        self.frames = [dict(number=n, unit=True) for n in range(4445)]
        self.overrides = {}
        self.counts = {}
        self.close_full = []
        self.prefix_bad = False
        self.physical_bad = False

    def validate(self):
        self.inventory.write_bytes(canonical(self.frames)+b'\n')
        physical = file_sha(self.path)
        members = [dict(frames=n, encoded_prefix_bytes=n,
                        encoded_prefix_sha256=physical,
                        decoded_canonical_sha256='UNIT') for n in (2223,4445)]
        binding = dict(physical_bytes=self.path.stat().st_size,
                       physical_sha256=physical,
                       frame_inventory_sha256=file_sha(self.inventory), members=members)
        outer = self
        class UnitReader:
            def __init__(self, path, expected):
                self.count = 0
                self.file = open(path,'rb')
            def next(self):
                n = self.count
                count = outer.counts.get(n,284)
                block = dict(parentSlot=999+n, blockhash=f'h{1000+n}',
                             previousBlockhash=f'h{999+n}',
                             blockTime=(1800000000*1000000+n*270000)//1000000-1,
                             transactions=[dict(meta=dict(err={'UNIT':1} if i<count else None)) for i in range(512)])
                body = dict(slot=1000+n, block=block)
                for key,value in outer.overrides.get(n,{}).items():
                    (body if key=='slot' else block)[key] = value
                self.count += 1
                return canonical(dict(params=dict(result=dict(value=body)))),dict(number=n,unit=True)
            def receipt(self):
                row = dict(next(m for m in members if m['frames']==self.count))
                if outer.prefix_bad:row['decoded_canonical_sha256']='CHANGED'
                return row
            def close(self, *, full=False):
                outer.close_full.append(full)
                self.file.close()
                row=dict(self.receipt(),valid=True)
                if outer.physical_bad:row['encoded_prefix_sha256']='CHANGED'
                return row
        with patch.object(tape,'workload',return_value=dict(tape_binding=binding)),patch.object(tape,'Reader',UnitReader):
            return tape.validate_existing(self.path,self.inventory,kind='A')

    def test_frozen_lane_count_and_preserved_template_errors_derive_total(self):
        source=Path(os.environ['MM_V3_CANDIDATE_CHECKOUT'])
        binding=workload('A')['tape_binding']
        spec_path=source/binding['spec']['path']
        template_path=source/binding['template']['path']
        self.assertEqual(file_sha(spec_path),binding['spec']['sha256'])
        self.assertEqual(file_sha(template_path),binding['template']['sha256'])
        spec=json.loads(spec_path.read_bytes())
        templates=json.loads(gzip.decompress(template_path.read_bytes()))
        self.assertEqual(spec['transaction_mix'],binding['transaction_mix'])
        failures={lane:sum(lane=='failed' or templates['pumpswap' if lane=='failed' else lane][i%len(templates['pumpswap' if lane=='failed' else lane])]['meta']['err'] is not None
                          for i in range(count)) for lane,count in spec['transaction_mix'].items()}
        self.assertEqual(failures,dict(failed=256,meteora=28,pump=0,pumpswap=0))
        self.assertEqual(sum(failures.values()),284)
        self.assertEqual(sum(spec['transaction_mix'].values())-sum(failures.values()),228)

    def test_exact_population_is_required_through_all_4445_frames(self):
        result=self.validate()
        self.assertTrue(result['valid'])
        self.assertEqual(result['frames_validated'],4445)
        self.assertEqual(set(result['checkpoints']),{'2223','4445'})
        self.assertEqual(self.close_full,[True])
        self.assertEqual(result['source_frames_released'],0)

    def test_256_and_neighboring_totals_fail_at_first_and_last_frame(self):
        for count in (256,283,285):
            for number in (0,4444):
                with self.subTest(count=count,number=number):
                    self.counts={number:count}
                    with self.assertRaisesRegex(ValueError,'failed_transaction_mix'):self.validate()

    def test_failure_rule_is_not_special_cased_to_native_prefix_or_checkpoint(self):
        for number in (1,239,240,2222,2223,2224,4443):
            with self.subTest(number=number):
                self.counts={number:283}
                with self.assertRaisesRegex(ValueError,'failed_transaction_mix'):self.validate()

    def test_neighboring_clock_and_shape_invariants_remain_strict(self):
        bad=dict(slot=0,parentSlot=0,blockhash='wrong',previousBlockhash='wrong',blockTime=0,
                 transactions=[dict(meta=dict(err=None))]*511)
        for key,value in bad.items():
            with self.subTest(field=key):
                self.overrides={0:{key:value}}
                with self.assertRaisesRegex(ValueError,'immutable_event_clock_or_shape'):self.validate()

    def test_frame_inventory_identity_remains_required(self):
        self.frames[0]['number']=1
        with self.assertRaisesRegex(ValueError,'frame_inventory_bytes'):self.validate()

    def test_prefix_binding_remains_required(self):
        self.prefix_bad=True
        with self.assertRaisesRegex(ValueError,'tape_prefix_binding'):self.validate()

    def test_final_physical_binding_remains_required(self):
        self.physical_bad=True
        with self.assertRaisesRegex(ValueError,'physical_tape_sha256'):self.validate()

    def test_production_AST_delta_is_only_the_total_failure_literal(self):
        repo=Path(__file__).resolve().parents[3]
        relative='diagnostics/stage-e-native-v3-executable-harness/harness/tape.py'
        original=subprocess.check_output(['git','-C',str(repo),'show','f480c6b4f7a8442fd148c7ed61bcc4447edaefca:'+relative])
        before=ast.parse(original)
        after=ast.parse(Path(tape.__file__).read_bytes())
        nodes=[n for n in ast.walk(after) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Call)
               and isinstance(n.left.func,ast.Name) and n.left.func.id=='sum']
        self.assertEqual(len(nodes),1)
        self.assertEqual(ast.literal_eval(nodes[0].comparators[0]),284)
        nodes[0].comparators[0].value=256
        self.assertEqual(ast.dump(before,include_attributes=False),ast.dump(after,include_attributes=False))


if __name__=='__main__':unittest.main()
