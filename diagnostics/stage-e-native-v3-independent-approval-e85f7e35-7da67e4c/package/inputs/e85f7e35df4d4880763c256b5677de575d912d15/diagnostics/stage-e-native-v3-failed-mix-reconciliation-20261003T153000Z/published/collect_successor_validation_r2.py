"""Nonmaterial conformity validation; no allocation, ledger, feeder, or trial."""
import hashlib,importlib.util,io,json,os,shutil,subprocess,sys,time,unittest
from pathlib import Path
sys.dont_write_bytecode=True
REPO=Path(os.environ['MM_SUCCESSOR_REPOSITORY']).resolve()
PKG=REPO/'diagnostics/stage-e-native-v3-executable-harness'
MOUNT=Path('/mnt/volume_nyc1_1790918115030');OLD=MOUNT/'meme-machine-observer-v2-7a516a6a'
OUTPUT=MOUNT/'stage-e-native-v3-paper-preflight/native-v3-failed-mix-reconciliation-20261003T153000Z-nonmaterial-validation-r2'
OUTPUT.mkdir(exist_ok=False)
sys.path.insert(0,str(PKG/'harness'))
import core,binding,attest,tape
spec=importlib.util.spec_from_file_location('review',PKG/'review.py');review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
RESULT=dict(paper_only=True,nonmaterial_only=True,stage_e='RED',stage_f='NOT STARTED',A_trials_started=0,A_slots_consumed=0,source_frames_released=0,Stage_A_admitted=False)
def save(name,value):
 data=core.canonical(value)+b'\n'
 with (OUTPUT/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 attest.fsync_dir(OUTPUT)
def subset(label,suite):
 stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
 (OUTPUT/(label+'.log')).write_text(stream.getvalue())
 row=dict(tests_run=result.testsRun,passed=result.wasSuccessful(),failed=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),source_frames_released=0)
 save(label+'.json',row);core.require(row['passed'] and row['skipped']==0,label+'_failed');return row
try:
 review_source=Path('/workspace/stage-e-conformity-review-candidate-20261003T153000Z-r2')
 core.require(not review_source.exists(),'review_candidate_namespace_already_exists')
 subprocess.run(['git','-C',str(REPO),'worktree','add','--detach',str(review_source),core.S],check=True,capture_output=True)
 os.environ['MM_V3_CANDIDATE_CHECKOUT']=str(review_source)
 save('REVIEW_CANDIDATE_HISTORY_BINDING.json',dict(candidate=binding.candidate_integrity(review_source),source=str(review_source),procedure='Unchanged review workflow: fresh detached S worktree from complete repository history',original_candidate_checkout_unchanged=True,reason='Old executor candidate clone lacks historical review commit objects required by the unchanged source_integrity test'))
 original_manifest=review.verify_package();save('SUCCESSOR_INPUT_MANIFEST_IDENTITY.json',dict(commit=os.environ.get('GITHUB_SHA'),manifest_sha256=core.file_sha(PKG/'package-manifest.json'),verified_artifacts=len(original_manifest['artifacts'])))
 runtime_before=binding.runtime_identity(OLD/'assembly/source');save('RUNTIME_BEFORE.json',runtime_before)
 core.require(runtime_before['python']=='3.12.14','selected_runtime_invalid')
 save('REVIEW_PROCESS_RESOURCE_OBSERVATION.json',attest.inspect([str(MOUNT)],os.getpid()))
 results=review.check();core.require(results['tests_run']==377 and results['passed'] and results['skipped']==0,'complete_successor_review_failed')
 save('FULL_DETERMINISTIC_TEST_RESULTS.json',results)
 sys.path.insert(0,str(core.CONTRACT));import static_validation;static_validation.SOURCE=review_source
 loader=unittest.TestLoader();contract=subset('INDEPENDENT_CONTRACT_SUITE',loader.discover(str(core.CONTRACT),pattern='test_*.py'));core.require(contract['tests_run']==55,'approved_contract_test_count')
 sys.path.insert(0,str(PKG/'tests'))
 names=['test_cgroup_applicability','test_envelope','test_resource_interval','test_signatures','test_resource_rules.ResourceRulesTests']
 resource=subset('INDEPENDENT_PURE_RESOURCE_SUITE',unittest.TestSuite(loader.loadTestsFromName(n) for n in names));core.require(resource['tests_run']==104,'pure_resource_test_count')
 print(json.dumps(dict(phase='deterministic_validation_complete',tests=377,contract_tests=55,pure_resource_tests=104,A_slots_consumed=0,source_frames_released=0)),flush=True)
 # Reproduce the unchanged predecessor rejection, never modify its source.
 original=subprocess.check_output(['git','-C',str(REPO),'show','f480c6b4f7a8442fd148c7ed61bcc4447edaefca:diagnostics/stage-e-native-v3-executable-harness/harness/tape.py'])
 oldfile=OUTPUT/'PREDECESSOR_TAPE_VERIFIER.py';oldfile.write_bytes(original)
 spec=importlib.util.spec_from_file_location('predecessor_tape_verifier',oldfile);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
 try:old.validate_existing(OLD/'tape/full-cohort-v2.tape',OLD/'tape/FRAMES.json',kind='A')
 except ValueError as exc:
  core.require(str(exc)=='failed_transaction_mix','unexpected_predecessor_rejection');save('PREDECESSOR_TAPE_REJECTION.json',dict(rejection=str(exc),source_sha256=core.sha(original),source_frames_released=0))
 else:raise ValueError('predecessor_unexpectedly_accepted')
 started=time.time_ns();receipt=tape.validate_existing(OLD/'tape/full-cohort-v2.tape',OLD/'tape/FRAMES.json',kind='A')
 save('COMPLETE_EXISTING_TAPE_VALIDATION.json',dict(receipt,validation_started_utc_ns=started,validation_ended_utc_ns=time.time_ns(),native_service_started=False,feeder_started=False,ledger_created=False))
 print(json.dumps(dict(phase='full_existing_tape_verified',frames=receipt['frames_validated'],physical_sha256=receipt['physical_sha256'],source_frames_released=0)),flush=True)
 # Independent equality to all 240 native prefix frames; pure construction only.
 sys.path.insert(0,str(OLD/'assembly/source'))
 from certification.stage_e_native_v2 import fixtures
 reader=tape.Reader(OLD/'tape/full-cohort-v2.tape',core.workload('A')['tape_binding']['members'][-1]);rows=[]
 try:
  for number in range(240):
   raw,row=reader.next();native=fixtures.build_frame('run380',number);core.require(raw==native,'native_prefix_fixture_inequality:'+str(number))
   body=json.loads(raw)['params']['result']['value']['block'];core.require(sum(t['meta']['err'] is not None for t in body['transactions'])==284,'native_prefix_failed_population')
   rows.append(dict(number=number,payload_sha256=core.sha(raw),payload_bytes=len(raw),total_transactions=512,failed_transactions=284,successful_transactions=228))
 finally:reader.close(strict=False)
 save('ALL_240_NATIVE_PREFIX_EQUALITY.json',dict(candidate_sha=core.S,candidate_tree=core.T,fixture_source_sha256=core.file_sha(Path(fixtures.__file__)),frames_compared=240,every_native_prefix_frame_exactly_equal=True,frames=rows,source_frames_released=0,construction_only_no_native_service=True))
 runtime_after=binding.runtime_identity(OLD/'assembly/source');save('RUNTIME_AFTER.json',runtime_after)
 core.require(all(runtime_before[k]==runtime_after[k] for k in runtime_before if k!='mapped_libraries'),'runtime_file_identity_changed_during_review')
 core.require(all(runtime_before['mapped_libraries'][k]==runtime_after['mapped_libraries'][k] for k in set(runtime_before['mapped_libraries'])&set(runtime_after['mapped_libraries'])),'mapped_library_bytes_changed')
 save('RUNTIME_STABILITY.json',dict(all_runtime_fields_except_process_import_maps_identical=True,common_library_file_hashes_identical=True,stdlib_digest=runtime_after['stdlib_digest'],runtime_repair_performed=False,system_python_changed=False))
 # Preserve reviewed identities; refresh only changed deterministic evidence and package manifest.
 core.require(binding.infrastructure_identity()==core.read(PKG/'source_hashes.json'),'successor_source_identity_changed')
 (PKG/'package-manifest.json').write_bytes(core.canonical(review.package_manifest())+b'\n');review.verify_package()
 target=OUTPUT/'successor-repository';destination=target/'diagnostics/stage-e-native-v3-executable-harness';destination.parent.mkdir(parents=True);shutil.copytree(PKG,destination)
 workflow=target/'.github/workflows/stagee-native-v3-executable-review.yml';workflow.parent.mkdir(parents=True);shutil.copy2(REPO/'.github/workflows/stagee-native-v3-executable-review.yml',workflow)
 save('SUCCESSOR_FINAL_IDENTITIES.json',dict(infrastructure=binding.infrastructure_identity(),manifest_sha256=core.file_sha(PKG/'package-manifest.json'),verified_artifacts=len(core.read(PKG/'package-manifest.json')['artifacts']),candidate=binding.candidate_integrity(OLD/'candidate-checkout'),contract=binding.contract_integrity(REPO),tape=receipt,workload_sha256=core.sha(core.canonical(core.workload('A'))),independent_external_review='REQUIRED_NOT_SELF_SATISFIED',material_preflight='NOT_STARTED_PENDING_SUCCESSOR_REVIEW'))
 RESULT.update(status='FAILED_TRANSACTION_MIX_REPAIRED_AND_NONMATERIALLY_VERIFIED',root_cause='CONTRACT_IMPLEMENTATION_MISMATCH',full_tests=377,contract_tests=55,pure_resource_tests=104,full_tape_frames_verified=4445,native_prefix_frames_exact=240,successor_manifest_sha256=core.file_sha(PKG/'package-manifest.json'),infrastructure_digest=binding.infrastructure_identity()['digest'],mandatory_independent_review_pending=True,material_preflight_complete=False)
except Exception as exc:RESULT.update(validation_error_type=type(exc).__name__,validation_error=str(exc))
finally:
 save('FINAL_RESULT.json',RESULT)
 for name in ['unit_validation.log','test_results.json']:
  source=PKG/'evidence'/name
  if source.is_file():shutil.copy2(source,OUTPUT/('PRESERVED_'+name))
 artifacts=[dict(path=str(p.relative_to(OUTPUT)),bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.rglob('*')) if p.is_file()]
 save('MANIFEST.json',dict(artifacts=artifacts,paper_only=True,A_slots_consumed=0,source_frames_released=0))
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUTPUT)+'\n')
 print(json.dumps(RESULT,sort_keys=True),flush=True)
 if 'validation_error' in RESULT:raise SystemExit(1)
