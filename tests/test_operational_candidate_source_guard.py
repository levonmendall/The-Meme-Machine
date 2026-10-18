"""Complete frozen operational inverse; every original economic guard still runs."""
from tests.test_native_audit_source_guard import audit_predecessor, audit_predecessor_runtime_delta
from tests.test_ea_performance_source_guard import performance_source, performance_guard_source
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'tests/fixtures/operational_candidate_source_delta.json'
MANIFEST_SHA256='f1982ceef86d7acab5666c66bf951651d0f565dfd765300b691195b372f1b79c'
BASE='780f4015efd9fba528e97223f8e8e3b1a7322e12'
BASE_TREE='7646978bbfb2076aea90625c3c4a32cd4556491c'
BASE_GUARDS={
    'tests/test_pump_restore_source_guard.py':'b65170a1c90e628901b167ab8d73308ec055f13d8b597cad91c5f04b196172c1',
    'tests/test_robinhood_usd_valuation.py':'025ffbfc71a288edda446ce8aed0a31134e56b9e2c56df9a4d65d029a67fc5a1',
}
IMPLEMENTATION='f00a7727d9f64926aa36e1044f854c5ed91df990'
IMPLEMENTATION_TREE='fba8f9b10a7dc9d8d09201d801b8d8eda2d106b6'
PONS_PATHS=('meme_machine/lanes/pons/pons_selective_cohort.py',
       'meme_machine/runtime/robinhood/pons.py','meme_machine/runtime/robinhood/plane.py')
PATHS=(
    'engineering/diagnostics/current_combined_observation_20261014.py',
    'meme_machine/lanes/pons/pons_selective_cohort.py',
    'meme_machine/operational/lane.py',
    'meme_machine/runtime/candidate_restore_reads.py',
    'meme_machine/runtime/evidence_worker.py',
    'meme_machine/runtime/operation_costs.py',
    'meme_machine/runtime/robinhood/plane.py',
    'meme_machine/runtime/robinhood/pons.py',
    'meme_machine/runtime/status.py',
    'meme_machine/runtime/survivor_history.py',
    'meme_machine/solana_evidence_control.py',
    'meme_machine/solana_evidence_service.py',
    'meme_machine/solana_maintenance_runtime.py',
    'meme_machine/solana_maintenance_state.py',
    'meme_machine/solana_owner_admission.py',
    'meme_machine/solana_source_drain.py',
)


def manifest(test):
    raw=MANIFEST.read_bytes()
    test.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256,
        'complete reviewed operational candidate manifest')
    value=json.loads(raw)
    test.assertEqual(value['schema'],'authenticated-operational-candidate-source-delta-v1')
    test.assertEqual((value['base'],value['base_tree'],value['implementation'],value['implementation_tree']),
        (BASE,BASE_TREE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(value['guard_reference'],BASE,'legacy guard originals come from approved 780')
    test.assertEqual(set(value['files']),set(PATHS),'sixteen complete changed runtime sources only')
    return value


def candidate_source_predecessor(test,relative,current):
    """Only active complete sources enter here, before every original layer.

    No controller/AST exemption or fallback accepts an unknown successor.
    Older intermediate bytes are still tested by their original predecessors.
    """
    if relative not in PATHS:return current
    return _inverse(test,relative,current,manifest(test)['files'][relative])


def original_guard_source(test,relative,current):
    """Reverse fixed active-read hooks before the original guard-file checksum."""
    value=manifest(test)
    test.assertIn(relative,value['guards'])
    return _inverse(test,relative,current,value['guards'][relative])


def _inverse(test,relative,current,record):
    if isinstance(current,str):current=current.encode()
    checksum=hashlib.sha256(current).hexdigest()
    if checksum==record['before_sha256']:
        test.assertEqual(len(current),record['before_bytes']);return current
    test.assertEqual(checksum,record['after_sha256'],relative+':complete reviewed operational successor')
    test.assertEqual(len(current),record['after_bytes'])
    restored=current
    for change in record['changes']:
        before,after=(change[key].encode() for key in ('before','after'))
        test.assertTrue(after,relative+':explicit reversible addition/replacement')
        test.assertEqual(restored.count(after),1,relative+':one exact reviewed source delta')
        restored=restored.replace(after,before,1)
    test.assertEqual(hashlib.sha256(restored).hexdigest(),record['before_sha256'],
        relative+':all original source bytes restored')
    test.assertEqual(len(restored),record['before_bytes'])
    from tests.test_robinhood_usd_valuation import rally_delta
    test.assertEqual(rally_delta(restored,current),{key:record[key] for key in ('nodes','layouts')},
        relative+':exact statements/methods, headers and order')
    return restored


class OperationalCandidateSourceGuardTests(unittest.TestCase):
    def test_sixteen_complete_sources_reverse_exactly_to_approved_780(self):
        value=manifest(self)
        for relative,record in value['files'].items():
            current=performance_source(self,relative,audit_predecessor(self,relative,(ROOT/relative).read_bytes()))
            with self.subTest(relative=relative):
                self.assertEqual(hashlib.sha256(current).hexdigest(),record['after_sha256'])
                before=candidate_source_predecessor(self,relative,current)
                self.assertEqual(hashlib.sha256(before).hexdigest(),record['before_sha256'])
                self.assertEqual(candidate_source_predecessor(self,relative,before),before)

    def test_original_guards_reverse_exactly_and_only_active_read_dispatch_changes(self):
        from engineering.diagnostics.build_operational_candidate_source_proof import calls
        value=manifest(self)
        declaration="'tests.test_operational_candidate_source_guard',"
        for relative in ('operational/tests.py','.github/workflows/ci.yml'):
            self.assertEqual((ROOT/relative).read_text().count(declaration),1,
                relative+':complete source proof must execute in both FAST and focused hosted checks')
        self.assertEqual(set(value['guards']),{
            'tests/test_pump_restore_source_guard.py','tests/test_robinhood_usd_valuation.py'})
        expected={
            'tests/test_pump_restore_source_guard.py':{
                'module/FunctionDef:authenticated_helper','module/FunctionDef:pump_restore_predecessor',
                'module/ClassDef:PumpRestoreSourceGuardTests/FunctionDef:test_legacy_guard_file_reverses_only_ten_active_reads_and_one_import'},
            'tests/test_robinhood_usd_valuation.py':{
                'module/ClassDef:RobinhoodUSDTests/FunctionDef:test_native_startup_failure_delta_preserves_all_prior_authority_and_source_guards',
                'module/ClassDef:RobinhoodUSDTests/FunctionDef:test_source_recorder_publication_reverses_only_exact_diagnostic_transport_and_test_read',
                *('module/ClassDef:RobinhoodUSDTests/FunctionDef:'+name for name in (
                    'test_maintenance_entry_clock_preserves_exact_original_leases_and_native_guards',
                    'test_buffered_origin_geometry_preserves_unique_full_obligation_and_original_authority',
                    'test_buffered_prejoin_replay_preserves_original_partition_and_full_ack_authority',
                    'test_preparation_replay_preserves_terminal_incident_and_original_full_ack_authority',
                    'test_prejoin_observation_preserves_exact_incident_gaps_and_full_ack_authority',
                    'test_session_economic_recovery_preserves_original_incidents_and_exact_full_proofs',
                    'test_recovered_economic_boundary_preserves_failed_census_and_all_previous_guards',
                    'test_program_gap_boundary_reverses_exactly_without_weakening_recovery_or_funding'))},
        }
        for relative,record in value['guards'].items():
            self.assertEqual(record['before_sha256'],BASE_GUARDS[relative],
                'whole original guard hash is independently pinned to approved 780')
            current=performance_guard_source(self,relative,audit_predecessor(self,relative,(ROOT/relative).read_bytes()))
            self.assertEqual(hashlib.sha256(current).hexdigest(),record['after_sha256'])
            restored=original_guard_source(self,relative,current)
            self.assertEqual(hashlib.sha256(restored).hexdigest(),record['before_sha256'],
                'all original assertions, constants, mutations and predecessors remain byte identical')
            self.assertEqual(set(record['nodes']),expected[relative]);self.assertEqual(record['layouts'],{})
            self.assertEqual(calls(current),record['fixed_read_hooks'])
            self.assertIn(b'assertEqual',current)
            for changed in (current+b'\n# unknown guard change\n',
                    current.replace(b'assertEqual',b'assertNotEqual',1)):
                with self.subTest(relative=relative),self.assertRaises(AssertionError):
                    original_guard_source(self,relative,changed)

    def test_only_declared_owner_checkpoint_and_protection_nodes_change(self):
        rows=manifest(self)['files']
        self.assertEqual(set(rows[PONS_PATHS[0]]['nodes']),{
            'module/FunctionDef:_checkpoint','module/FunctionDef:run'})
        self.assertEqual(rows[PONS_PATHS[0]]['layouts'],{})
        self.assertEqual(set(rows[PONS_PATHS[1]]['nodes']),{
            'module/ImportFrom:0:contextlib','module/FunctionDef:save_cohort_checkpoint'})
        self.assertEqual(set(rows[PONS_PATHS[1]]['layouts']),{'module'})
        nodes=set(rows[PONS_PATHS[2]]['nodes']);loops={node for node in nodes if node.startswith('module/For:')}
        self.assertEqual(len(loops),1)
        self.assertEqual(nodes-loops,{
            "module/Assign:Name(id='_PROTECTION_SCHEMA', ctx=Store())",
            'module/Import:stat','module/FunctionDef:_schema_sql',
            *('module/ClassDef:Plane/FunctionDef:'+name for name in (
                '__init__','_protection_facts','_protection_generation','borrow_checkpoint',
                'close','maintain','transaction'))})
        self.assertEqual(set(rows[PONS_PATHS[2]]['layouts']),{'module','module/ClassDef:Plane'})

    def test_cancelled_source_exact_admission_and_original_full_recovery_guards_are_pinned(self):
        relative='meme_machine/solana_source_drain.py';record=manifest(self)['files'][relative]
        self.assertEqual(set(record['nodes']),{
            "module/Assign:Name(id='CANCELLED_BUFFERED_CENSUS_SHA256', ctx=Store())",
            "module/Assign:Name(id='CANCELLED_BUFFERED_LEDGER_SHA256', ctx=Store())",
            *('module/FunctionDef:'+name for name in ('_buffered_log_inputs','_economic_recovery_inputs',
                'current_economic_recovery_descriptor','verify_economic_recovery_descriptor'))})
        self.assertEqual(set(record['layouts']),{'module'})
        current=(ROOT/relative).read_bytes()
        pairs=((b'd01237f6fa0e819de4ab6b8c3068f6c8ba5565fec67d20d1780c7b302dd0caec',b'f'*64),
            (b'97cafc5760e592ef574954bb49ba2b271852b676c66a504cfb73a9d55d9876b6',b'e'*64),
            (b'_cancelled_source=False',b'_cancelled_source=True'),
            (b"body.get('unexpected_cancellation',False) is _cancelled_source",b'True'),
            (b"hashlib.sha256(handlers.encode()).hexdigest()==CANCELLED_BUFFERED_LEDGER_SHA256",b'True'),
            (b"body['closed_sessions']==2",b"body['closed_sessions']>=1"),
            (b'original_source_drain_pass=False',b'original_source_drain_pass=True'))
        for before,after in pairs:
            self.assertIn(before,current,relative+':actual guarded input or disposition')
            with self.subTest(before=before),self.assertRaises(AssertionError):
                candidate_source_predecessor(self,relative,current.replace(before,after,1))
        declaration="'tests.test_cancelled_buffered_recovery',"
        for path in ('operational/tests.py','.github/workflows/ci.yml'):
            self.assertEqual((ROOT/path).read_text().count(declaration),1,
                path+':actual cancelled-source behavioral regressions must execute')

    def test_unknown_truncated_or_partially_reversed_source_never_passes(self):
        for relative,record in manifest(self)['files'].items():
            current=performance_source(self,relative,audit_predecessor(self,relative,(ROOT/relative).read_bytes()))
            mutations=[b'',current+b'\n# unknown successor\n']
            for change in record['changes']:
                changed=current.replace(change['after'].encode(),change['before'].encode(),1)
                self.assertNotEqual(changed,current)
                # A one-delta file reverses completely to the explicitly pinned
                # legitimate predecessor, rather than an unknown partial source.
                if hashlib.sha256(changed).hexdigest()==record['before_sha256']:
                    self.assertEqual(candidate_source_predecessor(self,relative,changed),changed)
                else:mutations.append(changed)
            for changed in mutations:
                with self.subTest(relative=relative,sha256=hashlib.sha256(changed).hexdigest()),self.assertRaises(AssertionError):
                    candidate_source_predecessor(self,relative,changed)

    def test_protection_expiry_scope_raw_writes_rollback_and_borrow_guards_cannot_be_weakened(self):
        mutations={
            'engineering/diagnostics/current_combined_observation_20261014.py':(
                (b"db.execute('PRAGMA query_only=ON')",b"db.execute('PRAGMA query_only=OFF')"),
                (b"row.get('trigger_active_bracket') is not True",b'False')),
            'meme_machine/operational/lane.py':((b"self.lane!='pons'",b'False'),),
            'meme_machine/runtime/candidate_restore_reads.py':((b'SNAPSHOT_SECONDS = .025',b'SNAPSHOT_SECONDS = 1'),
                (b'if self.cancelled():',b'if False:')),
            'meme_machine/runtime/operation_costs.py':((b'if not enabled():',b'if False:'),),
            'meme_machine/runtime/status.py':((b'STARTUP_STACK_MIN_SECONDS=5.',b'STARTUP_STACK_MIN_SECONDS=0.'),
                (b'function in allowed_frames.get(module,())',b'True')),
            'meme_machine/runtime/survivor_history.py':((b'with native_startup_replay(requested.is_set):',b'with native_startup_replay(lambda:False):'),),
            PONS_PATHS[0]:((b'plane=queue.plane',b'plane=None'),
                (b"queue.plane.get(identity)['generation']!=scheduled['work']['generation']",b'False')),
            PONS_PATHS[1]:((b'with nullcontext(plane) if owned else plane.borrow_checkpoint(path):',b'with nullcontext(plane):'),
                (b'if owned:plane.close()',b'plane.close()')),
            PONS_PATHS[2]:((b'self.db.execute(\'PRAGMA quick_check\')',b'self.db.execute(\'PRAGMA schema_version\')'),
                (b'candidate_protection_runtime_',b'ignored_protection_runtime_'),
                (b"OLD.key='pons_cohort'",b'0'),(b"substr(OLD.key,1,16)='native_position:'",b'0'),
                (b"cached[3]==scope",b'True'),(b"if status!='settled':protected.add(candidate)",b'pass'),
                (b'now-86400',b'now-1'),(b'if pending_protection is not None and self._protection_generation()!=pending_protection[0]:',b'if False:'),
                (b'threading.get_ident()!=self._owner_thread',b'False'),(b'self._owner_inode',b'None')),
        }
        for relative,pairs in mutations.items():
            current=performance_source(self,relative,audit_predecessor(self,relative,(ROOT/relative).read_bytes()))
            for before,after in pairs:
                self.assertIn(before,current,relative+':real guarded source fragment')
                with self.subTest(relative=relative,before=before),self.assertRaises(AssertionError):
                    candidate_source_predecessor(self,relative,current.replace(before,after,1))

    def test_manifest_change_is_refused_and_unrelated_source_is_not_normalized(self):
        original=MANIFEST.read_bytes();read=Path.read_bytes
        for changed in (original+b'\n',b'{}',original.replace(BASE.encode(),b'f'*40,1)):
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()),\
                    patch.object(Path,'read_bytes',new=lambda path:changed if path==MANIFEST else read(path)),\
                    self.assertRaises(AssertionError):
                candidate_source_predecessor(self,PONS_PATHS[0],(ROOT/PONS_PATHS[0]).read_bytes())
        self.assertEqual(candidate_source_predecessor(self,'unrelated/source.py',b'unchanged'),b'unchanged')

    def test_maintenance_boundaries_keyset_and_fixed_failure_codes_are_pinned(self):
        mutations={
            'meme_machine/solana_evidence_control.py':(
                (b"if ticket.state=='ACCEPTED':return False",b'if False:return False'),
                (b'if spending and accepted_at>=ticket.permit_deadline:',b'if False:'),
                (b'now+MAINTENANCE_PERMIT_SECONDS',b'now+MAINTENANCE_PERMIT_SECONDS+1'),
                (b'priority!=4 or self._checkpoint_busy or self._checkpoint_handoff is not None',b'False'),
                (b'len(self.queue)+reserved>=limit',b'len(self.queue)>=limit')),
            'meme_machine/solana_evidence_service.py':(
                (b'ticket=await admission.boundary(deadline,stop)',b'ticket=None'),
                (b'if ticket is None or stop.is_set():break',b'if False:break'),
                (b'if ticket is not None:owner.cancel_maintenance_boundary(ticket)',b'if False:pass'),
                (b'owner.submit_maintenance(timed,maintenance_ticket)',b'owner.submit(timed)')),
            'meme_machine/solana_owner_admission.py':(
                (b'self.owner.request_maintenance_boundary(deadline=deadline)',
                    b'self.owner.request_maintenance_boundary(deadline=self.clock()+30)'),
                (b'timeout=max(0,deadline-self.clock())',b'timeout=30'),
                (b'if ticket is not None and not returned:',b'if False:')),
            'meme_machine/solana_maintenance_runtime.py':(
                (b'0<=submitted<=entered<=current',b'True'),
                (b'start=entered;owner_delay=entered-submitted',b'start=current;owner_delay=0'),
                (b'self._next_admission=(observation.monotonic+',b'self._next_admission=(self.monotonic()+'),
                (b'with self.execution_lease(start+self.leases.execution):',b'with self.execution_lease(current+self.leases.execution):')),
            'meme_machine/solana_maintenance_state.py':(
                (b'if after is not None and after[0]>=lower:',b'if after is not None:'),
                (b"where='scope=? AND '+compare+'>'+markers+' AND slot<?'",b'where=base'),
                (b"where+=' AND '+compare+'<='+markers",b'where+=\' AND 1\'')),
            'meme_machine/runtime/evidence_worker.py':(
                (b"'maintenance_boundary_command_missing'",b"'arbitrary_provider_error'"),),
        }
        self.assertEqual(set(mutations),set(PATHS)-{
            'engineering/diagnostics/current_combined_observation_20261014.py',
            'meme_machine/lanes/pons/pons_selective_cohort.py','meme_machine/operational/lane.py',
            'meme_machine/runtime/candidate_restore_reads.py','meme_machine/runtime/operation_costs.py',
            'meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/robinhood/pons.py',
            'meme_machine/runtime/status.py','meme_machine/runtime/survivor_history.py',
            'meme_machine/solana_source_drain.py'})
        for relative,pairs in mutations.items():
            current=(ROOT/relative).read_bytes()
            for before,after in pairs:
                self.assertIn(before,current,relative+':actual reviewed maintenance safeguard')
                with self.subTest(relative=relative,before=before),self.assertRaises(AssertionError):
                    candidate_source_predecessor(self,relative,current.replace(before,after,1))
        for module in ('test_maintenance_permit_ownership','test_maintenance_admission_service',
                'test_pipeline_retention_boundary'):
            declaration="'tests."+module+"',"
            for path in ('operational/tests.py','.github/workflows/ci.yml'):
                self.assertEqual((ROOT/path).read_text().count(declaration),1,
                    path+':actual maintenance/retention behavioral regressions execute once')
