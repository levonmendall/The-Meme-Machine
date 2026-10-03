"""Independent, finite approval checks. No admission, tape generation or service."""
import ast
import base64
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REF = 'e85f7e35df4d4880763c256b5677de575d912d15'
OLD = 'f480c6b4f7a8442fd148c7ed61bcc4447edaefca'
S = '7a516a6a92be9347661ac0e7f560971c171a0931'
C = '5ed5aef4dfe1bb7823037fe1ce440c193411a194'
G = 'dd75942dcc7498156f80808397c594a6767871e9'
B = 'diagnostics/stage-e-native-v3-executable-harness'
CB = 'diagnostics/stage-e-native-v3-production-envelope-contract'
PUB = 'diagnostics/stage-e-native-v3-failed-mix-reconciliation-20261003T153000Z/published'
CURRENT = ROOT/'inputs'/REF
PKG = CURRENT/B
NATIVE = ROOT/'inputs'/S
EVIDENCE = CURRENT/PUB

def read(path):
    return json.loads(Path(path).read_bytes())

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

baselines = read(ROOT/'retrieval/independent-baselines.json')
extra = read(ROOT/'retrieval/independent-extra.json')
for key, row in baselines['files'].items():
    commit, relative = key.split(':', 1)
    target = ROOT/'inputs'/commit/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(row['content'].encode())

current_tree = read_json = json.loads(extra['successor_tree']['content'])
assert not current_tree['truncated']
current = {r['path']:r for r in current_tree['tree'] if r['type']=='blob'}
candidate = json.loads(baselines['candidate_tree']['content'])
parent = json.loads(baselines['parent_tree']['content'])
assert not candidate['truncated'] and not parent['truncated']
native_rows = [r for r in candidate['tree'] if r['type']=='blob']
assert len(native_rows)==1241
old_rows = {r['path']:r for r in parent['tree'] if r['type']=='blob'}
publication_candidate_differences=[r['path'] for r in native_rows if
    (current[r['path']]['sha'],current[r['path']]['mode'])!=(r['sha'],r['mode'])]
assert publication_candidate_differences==['.github/workflows/non-market-certification.yml']
assert all((current[r['path']]['sha'],current[r['path']]['mode'])==
           (old_rows[r['path']]['sha'],old_rows[r['path']]['mode']) for r in native_rows)
delta = sorted(k for k in set(current)|set(old_rows) if current.get(k)!=old_rows.get(k))
# API entries include blob URLs, but identical object identities have identical URLs.
delta = sorted(k for k in set(current)|set(old_rows) if
               (current.get(k,{}).get('sha'),current.get(k,{}).get('mode')) !=
               (old_rows.get(k,{}).get('sha'),old_rows.get(k,{}).get('mode')))
assert all(k.startswith(B+'/') or k.startswith(PUB.removesuffix('/published')+'/') or
           k=='.github/workflows/stagee-native-v3-failed-mix-validation.yml' for k in delta)
executable_delta = [k for k in delta if k.startswith(B+'/harness/') or k in
                    [B+'/execute.py',B+'/review.py',B+'/verify_evidence.py']]
assert executable_delta == [B+'/harness/tape.py']
manifest = read(PKG/'package-manifest.json')
old_manifest = read(ROOT/'inputs'/OLD/B/'package-manifest.json')
new_by = {a['path']:a for a in manifest['artifacts']}
old_by = {a['path']:a for a in old_manifest['artifacts']}
assert all(new_by[a['path']]==a for a in old_manifest['artifacts'] if '/tests/' in a['path'])
assert new_by[B+'/EXECUTABLE_BINDINGS.json']==old_by[B+'/EXECUTABLE_BINDINGS.json']
before_path = ROOT/'inputs'/OLD/B/'harness/tape.py'
after_path = PKG/'harness/tape.py'
assert digest(before_path.read_bytes())==old_by[B+'/harness/tape.py']['sha256']
before, after = ast.parse(before_path.read_bytes()), ast.parse(after_path.read_bytes())
nodes = [n for n in ast.walk(after) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Call)
         and isinstance(n.left.func,ast.Name) and n.left.func.id=='sum']
assert len(nodes)==1 and isinstance(nodes[0].ops[0],ast.Eq) and len(nodes[0].ops)==1
assert isinstance(nodes[0].comparators[0],ast.Constant) and nodes[0].comparators[0].value==284
validate = next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='validate_existing')
loops = [n for n in ast.walk(validate) if isinstance(n,ast.For)]
assert len(loops)==1 and nodes[0] in list(ast.walk(loops[0]))
nodes[0].comparators[0].value=256
assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)

contract = ROOT/'inputs'/C/CB
assert digest((contract/'package_sha256.json').read_bytes())=='786308bcfc18c88f1c5e97286c311766159d592b47a637d2c6ae6ff53ffd22f0'
cm = read(contract/'package_sha256.json')
wr = next(a for a in cm['artifacts'] if a['path']=='production_capacity_workload.json')
assert digest((contract/'production_capacity_workload.json').read_bytes())==wr['sha256']
workload = read(contract/'production_capacity_workload.json')
binding = workload['tape_binding']
for key in ['fixture_source','spec','template']:
    a=binding[key];raw=(NATIVE/a['path']).read_bytes()
    assert len(raw)==a['bytes'] and digest(raw)==a['sha256']
generator_path=ROOT/'inputs'/G/binding['generator_source']['path']
assert digest(generator_path.read_bytes())==binding['generator_source']['sha256']
spec=read(NATIVE/binding['spec']['path'])
templates=json.loads(gzip.decompress((NATIVE/binding['template']['path']).read_bytes()))
assert spec['transaction_mix']==binding['transaction_mix']==dict(failed=256,meteora=128,pump=48,pumpswap=80)
assert len(templates['meteora'])==32
failed_indices=[i for i,tx in enumerate(templates['meteora']) if tx['meta']['err'] is not None]
assert failed_indices==[6,7,15,16,20,21,23]
assert not any(tx['meta']['err'] is not None for lane in ['pump','pumpswap'] for tx in templates[lane])
assert 128//32*len(failed_indices)==28

sys.path.insert(0,str(NATIVE))
from certification.stage_e_native_v2 import fixtures
function=next(n for n in ast.parse(generator_path.read_bytes()).body
              if isinstance(n,ast.FunctionDef) and n.name=='extended_frame')
namespace={'json':json}
exec(compile(ast.Module(body=[function],type_ignores=[]),str(generator_path),'exec'),namespace)
extend=namespace['extended_frame']
prefix=read(EVIDENCE/'verified-executor-validation/ALL_240_NATIVE_PREFIX_EQUALITY.json')
assert prefix['frames_compared']==240 and prefix['every_native_prefix_frame_exactly_equal']
assert prefix['fixture_source_sha256']==binding['fixture_source']['sha256']
assert [r['number'] for r in prefix['frames']]==list(range(240))
assert all(r['total_transactions']==512 and r['failed_transactions']==284 and r['successful_transactions']==228 for r in prefix['frames'])
constructed=[]
for n in [0,1,239,240,2222,4444]:
    raw=extend(n,fixtures,spec,templates)
    body=json.loads(raw)['params']['result']['value']
    txs=body['block']['transactions']
    assert len(txs)==512 and sum(tx['meta']['err'] is not None for tx in txs)==284
    offset=0;per_lane={}
    for lane,count in spec['transaction_mix'].items():
        part=txs[offset:offset+count];offset+=count
        per_lane[lane]=sum(tx['meta']['err'] is not None for tx in part)
        if lane!='failed':
            assert all(tx['meta']['err']==templates[lane][i%len(templates[lane])]['meta']['err'] for i,tx in enumerate(part))
    assert per_lane==dict(failed=256,meteora=28,pump=0,pumpswap=0)
    if n<240:
        assert raw==fixtures.build_frame('run380',n)
        assert digest(raw)==prefix['frames'][n]['payload_sha256'] and len(raw)==prefix['frames'][n]['payload_bytes']
    constructed.append(dict(number=n,payload_bytes=len(raw),sha256=digest(raw),failures_by_lane=per_lane,successes=228,native_prefix_receipt_compared=n<240))

sys.path.insert(0,str(PKG/'harness'));sys.path.insert(0,str(PKG/'tests'))
import core
core.CONTRACT=contract  # Read-only location of exact immutable contract inputs.
os.environ['MM_V3_CANDIDATE_CHECKOUT']=str(NATIVE)
from test_failed_transaction_mix import FailedTransactionMixTests
from test_tape_clock import TapeClockTests
suite=unittest.TestSuite(FailedTransactionMixTests(n) for n in unittest.defaultTestLoader.getTestCaseNames(FailedTransactionMixTests)
                        if n!='test_production_AST_delta_is_only_the_total_failure_literal')
reader_names=['test_exact_encoded_and_decoded_receipts','test_incomplete_prefix_fails','test_wrong_hash_fails',
              'test_extra_trailing_bytes_fails','test_truncated_record_fails','test_writable_tape_refused',
              'test_concatenated_gzip_and_decompression_bomb_refused']
suite.addTests(TapeClockTests(n) for n in reader_names)
stream=io.StringIO();run=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(ROOT/'bounded_tests.log').write_text(stream.getvalue())
assert run.wasSuccessful() and run.testsRun==15 and not run.skipped, stream.getvalue()

import binding as harness_binding
identity=harness_binding.infrastructure_identity()
assert identity==read(PKG/'source_hashes.json')
assert identity==read(ROOT/'inputs/02a282704ac1cdacdc35a3232d4553cc534f9bce'/B/'source_hashes.json')
full=read(EVIDENCE/'verified-executor-validation/FULL_DETERMINISTIC_TEST_RESULTS.json')
assert full['infrastructure']==identity and full['tests_run']==377 and full['passed']
assert full['failed']==full['errors']==full['skipped']==0
for label,count in [('INDEPENDENT_CONTRACT_SUITE',55),('INDEPENDENT_PURE_RESOURCE_SUITE',104)]:
    r=read(EVIDENCE/'verified-executor-validation'/(label+'.json'))
    assert r['tests_run']==count and r['passed'] and r['failed']==r['errors']==r['skipped']==0
tape=read(EVIDENCE/'verified-executor-validation/COMPLETE_EXISTING_TAPE_VALIDATION.json')
assert tape['binding_sha256']==digest(canonical(binding))
assert tape['physical_sha256']==binding['physical_sha256'] and tape['frame_inventory_sha256']==binding['frame_inventory_sha256']
assert tape['valid'] and tape['frames_validated']==4445 and tape['source_frames_released']==0
for n in [2223,4445]:
    member=next(r for r in binding['members'] if r['frames']==n)
    assert all(tape['checkpoints'][str(n)][k]==member[k] for k in tape['checkpoints'][str(n)])
restore=ROOT/'inputs'/OLD/'.github/workflows/stagee-native-v3-executable-review.yml'
assert restore.read_bytes()==(EVIDENCE/'verified-executor-validation/successor-repository/.github/workflows/stagee-native-v3-executable-review.yml').read_bytes()
assert restore.read_bytes()==(CURRENT/'.github/workflows/stagee-native-v3-executable-review.yml').read_bytes()

result=dict(version='native-v3-independent-successor-bounded-review-1',python=sys.version.split()[0],
    candidate_paths_unchanged_from_approved_parent=1241,publication_paths_matching_frozen_candidate=1240,
    preexisting_publication_only_CI_difference=publication_candidate_differences,
    frozen_candidate_identity_unchanged=True,changed_harness_executables=executable_delta,
    predecessor_tests_unchanged=True,AST_only_count_literal_changed=True,exact_equality_every_frame=True,
    generator_sha256=binding['generator_source']['sha256'],meteora_template_error_indices=failed_indices,
    forced_failures=256,preserved_meteora_failures=28,total_failures=284,total_successes=228,total_transactions=512,
    bounded_frame_constructions=constructed,targeted_tests=8,opaque_reader_tests=7,tests_run=15,failed=0,errors=0,skipped=0,
    infrastructure_digest=identity['digest'],validation_source_infrastructure_matches_successor=True,
    immutable_workload_sha256=digest(canonical(workload)),published_receipts_verified=dict(full=377,contract=55,resource=104,tape_frames=4445,native_prefix_frames=240),
    full_tape_scan_rerun=False,full_suites_rerun=False,source_frames_released=0,material_workloads=0,
    admission_performed=False,stage_e='RED',stage_f='NOT STARTED')
(ROOT/'bounded_checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
