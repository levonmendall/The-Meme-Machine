import ast,hashlib,json,unittest
from pathlib import Path
from operational.ramses_attribution import economic_sha256
ROOT=Path(__file__).resolve().parents[1]
class RamsesSourceAttributionTests(unittest.TestCase):
    def reference(self):
        return json.loads((ROOT/'operational/ramses-source-attribution.json').read_text())
    def test_every_materialized_module_matches_reconstructed_source(self):
        reference=self.reference()
        self.assertEqual(reference['source_reconstruction'],'PASS')
        self.assertEqual(reference['attribution'],'PASS')
        self.assertTrue(reference['composed_diff_match'])
        self.assertEqual(len(reference['patches']),18)
        self.assertEqual(len(reference['materialized_modules']),44)
        for row in reference['materialized_modules']:
            with self.subTest(module=row['path']):
                self.assertEqual(economic_sha256((ROOT/row['path']).read_bytes(),row['path']),
                    row['economic_AST_sha256'])
    def test_frozen_strategy_bytes_match_original_pinned_policy(self):
        reference=self.reference()
        frozen=reference['frozen_files']['robinhood_research/ramses_strategy.py']
        self.assertTrue(frozen['byte_unchanged'])
        self.assertEqual(hashlib.sha256((ROOT/'meme_machine/lanes/ramses/ramses_strategy.py').read_bytes()).hexdigest(),
            frozen['base_sha256'])
    def test_economic_mutations_cannot_pass_the_comparison(self):
        pairs=[('ramses_strategy.py','classify_pool'),('ramses_strategy.py','wide_range_capital_ceiling'),
            ('ramses_universe.py','_quote_side'),('ramses_strategy.py','_wide_range_ids'),
            ('ramses_strategy.py','_cost_total'),('ramses_strategy.py','controller_action'),
            ('ramses_all_pool_lifecycle.py','_unwind'),('ramses.py','quote_value')]
        for filename,function in pairs:
            path='meme_machine/lanes/ramses/'+filename
            original=(ROOT/path).read_text();tree=ast.parse(original)
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
            node.body=[ast.Return(value=ast.Constant(value=None))]
            changed=ast.unparse(ast.fix_missing_locations(tree))
            with self.subTest(behavior=function):
                self.assertNotEqual(economic_sha256(original,path),economic_sha256(changed,path))

    def test_optional_capability_fallback_normalizes_only_exact_reader(self):
        path='meme_machine/lanes/ramses/provider_topology.py'
        current=(ROOT/path).read_text()
        expanded='except (OSError,ValueError,KeyError,TypeError,AttributeError):pass'
        original='except (OSError,ValueError,KeyError):pass'
        self.assertEqual(current.count(expanded),1)
        baseline=current.replace(expanded,original)
        expected='6c23d1ee23fb5fa7b893e81ab3fd5cc1064268516ff1cd6896ca69bcfd227a7c'
        self.assertEqual(economic_sha256(baseline,path),expected)
        self.assertEqual(economic_sha256(current,path),expected)
        mutations=[current.replace(expanded,'except (OSError,ValueError,KeyError,TypeError,AttributeError,Exception):pass'),
            current.replace(expanded,'except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):pass'),
            current.replace("methods.get('eip1898_'+m,{}).get('supported') is True","methods.get('eip1898_'+m,{}).get('supported') is False")]
        for changed in mutations:
            self.assertNotEqual(changed,current)
            self.assertNotEqual(economic_sha256(changed,path),expected)

    def test_census_cleanup_preserves_transaction_and_provider_comparison(self):
        path='meme_machine/lanes/ramses/ramses_lifecycle_log_census.py'
        current=(ROOT/path).read_text()
        added=('    from contextlib import closing\n'
               '    with closing(sqlite3.connect(cache_path)) as db, db:\n')
        self.assertEqual(current.count(added),1)
        old=current.replace(added,'    with sqlite3.connect(cache_path) as db:\n')
        expected=economic_sha256(old,path)
        self.assertEqual(economic_sha256(current,path),expected)
        for changed in (current.replace('as db, db:', 'as db:'),
                        current.replace('max_logs=5000','max_logs=6000'),
                        current.replace("provider_role='public_observation'", "provider_role='canonical'")):
            self.assertNotEqual(economic_sha256(changed,path),expected)

    def test_approved_strategy_comparison_uses_current_exact_plumbing_rules(self):
        import subprocess,sys
        completed=subprocess.run([sys.executable,str(ROOT/'operational/strategy-change-audit.py')],
                                 cwd=ROOT,env={},capture_output=True,text=True,check=True)
        result=json.loads(completed.stdout)
        self.assertEqual(result['result'],'PASS')
        self.assertEqual(result['pre_change_commit'],'e34c38c78061834ad2892a897fcdd52fc438b061')
        self.assertEqual(result['ramses_economic_modules_unchanged'],44)
        self.assertTrue(result['entry_and_survivor_policies_only_approved_deltas'])
        self.assertTrue(result['owner_admission_scheduler_byte_identical_to_engineering_base'])
        from tests.test_robinhood_usd_valuation import RALLY_BASE,RALLY_SCHEMA,RALLY_MANIFEST_SHA256
        self.assertEqual(result['decision_policy_layer'],dict(schema=RALLY_SCHEMA,
            revision='paper-postgrad-rally-v1',predecessor_commit=RALLY_BASE,
            manifest_sha256=RALLY_MANIFEST_SHA256,verified=True))

    def test_strategy_audit_rejects_unapproved_decision_and_audit_source_changes(self):
        import runpy
        from unittest.mock import patch
        audit=ROOT/'operational/strategy-change-audit.py'
        original_read=Path.read_bytes
        mutations={
            'operational/strategy-change-audit.py':lambda raw:raw+b'\n# unreviewed audit mutation\n',
            'meme_machine/lanes/pump/pumpswap_survivor.py':lambda raw:raw.replace(
                b'minimum_age_seconds=600',b'minimum_age_seconds=599',1),
            'meme_machine/lanes/pons/pons_postgrad_survivor.py':lambda raw:raw.replace(
                b'max_creator_sell_quote=0',b'max_creator_sell_quote=1',1),
        }
        for relative,mutate in mutations.items():
            with self.subTest(source=relative):
                target=ROOT/relative;original=original_read(target);changed=mutate(original)
                self.assertNotEqual(changed,original,'negative mutation must change protected source')
                def read(path):return changed if path==target else original_read(path)
                with patch.object(Path,'read_bytes',new=read),self.assertRaises(AssertionError):
                    runpy.run_path(str(audit),run_name='__main__')
