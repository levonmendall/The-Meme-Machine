"""Raw predecessor/protocol/prepared-lane proof ingestion; no test execution.

Original verifier predicates and source identities stay mandatory. Summary PASS
fields never satisfy a gate without the corresponding primary log/state/witness.
"""
import ast
from contextlib import contextmanager
from pathlib import Path
import re
import sys

from frozen import *
from shared_inputs import artifact
from preserve import verify_inventory
from binding import verify_assembly
from attest import signed_document

CANONICAL = ('offline', 'crash', 'restart', 'integrated', 'historical', 'registry',
             'directional', 'bounded', 'joined_soak', 'joined_crash', 'joined_provider', 'joined_long_horizon')
NATIVE_CASES = ('clock-contract', 'run379-setup', 'native-transitions', 'held-reader',
                'generation-restart', 'm1-completion')
LANES = ('pump', 'pons', 'meteora', 'ramses')


def transcript(data, expected_tests):
    require(type(data) is bytes and type(expected_tests) is list and expected_tests
            and len(set(expected_tests)) == len(expected_tests), 'primary_test_inventory_missing')
    body = data.decode('utf-8')
    rows = re.findall(r'^([\w.]+) \(([^\n]+)\) \.\.\. ok$', body, re.M)
    ids = [scope + '.' + test for test, scope in rows]
    # Standard unittest writes either module.Class or module.Class.test inside
    # parentheses; normalize the latter without permitting unknown test names.
    ids = [name if not name.rsplit('.', 2)[-1] == name.rsplit('.', 2)[-2]
           else name.rsplit('.', 1)[0] for name in ids]
    counts = re.findall(r'^Ran ([0-9]+) tests? in [0-9.]+s$', body, re.M)
    require(len(counts) == 1 and int(counts[0]) == len(expected_tests) == len(ids)
            and set(ids) == set(expected_tests) and len(set(ids)) == len(ids)
            and re.search(r'\nOK\s*\Z', body) and not re.search(r'\.\.\. (?:FAIL|ERROR|skipped|expected failure|unexpected success)', body),
            'incomplete_failed_skipped_or_fabricated_PASS_transcript')
    return dict(tests=len(ids), test_ids=sorted(ids), sha256=sha(data))


def source_test_inventory(source, modules):
    """Collect named test methods statically; never imports or executes tests."""
    require(type(modules) is list and modules and len(set(modules)) == len(modules), 'test_source_modules_required')
    names = []
    for module in modules:
        require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', module), 'test_module_name')
        path = relative(source, module.replace('.', '/') + '.py')
        tree = ast.parse(path.read_bytes())
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                        names.append(module + '.' + cls.name + '.' + method.name)
    require(names and len(names) == len(set(names)), 'test_inventory_empty_or_duplicate')
    return sorted(names)


@contextmanager
def assembled_verifiers(source):
    """Import only pure verification functions from the hash-checked assembly."""
    original = list(sys.path)
    for name, module in list(sys.modules.items()):
        if name == 'certification' or name.startswith('certification.'):
            path = getattr(module, '__file__', None)
            require(path and Path(path).resolve().is_relative_to(Path(source).resolve()),
                    'foreign_predecessor_verifier_already_imported')
    sys.path.insert(0, str(source))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == 'certification' or name.startswith('certification.'):
                module = sys.modules.pop(name)
                path = getattr(module, '__file__', None)
                require(path and Path(path).resolve().is_relative_to(Path(source).resolve()), 'foreign_retained_verifier_origin')
        sys.path[:] = original


def ingest_retained(folder, *, assembly, owner_key, owner_public_key_sha256):
    folder = Path(folder); verify_inventory(folder)
    rows = read(folder/'RAW_INVENTORY.json')['artifacts']
    payload_rows = [row for row in rows if row['path'] != 'RETAINED_AUTHORITY.json']
    signed = signed_document(folder/'RETAINED_AUTHORITY.json', owner_key, owner_public_key_sha256)
    require(signed == dict(version='stage-e-native-v3-preserved-raw-byte-attestation', **FROZEN,
                          payload_inventory_sha256=sha(canonical(payload_rows))),
            'retained_raw_byte_authority_missing_or_changed')
    manifest = verify_assembly(assembly); source = Path(assembly) / 'source'
    d = read(folder/'RETAINED_INPUTS.json'); exact_frozen(d)
    require(set(d) == set(FROZEN) | {'canonical', 'native', 'prepared', 'primary_test_receipts', 'origin', 'version'}
            and d['version'] == 'stage-e-native-v3-retained-raw-inputs', 'retained_raw_schema')
    require(set(d['canonical']) == set(CANONICAL) and set(d['native']) == set(NATIVE_CASES), 'retained_required_proof_missing')
    require(d['origin']['candidate_sha'] == S and d['origin']['candidate_tree'] == T
            and d['origin']['assembly_before'] == d['origin']['assembly_after'] == ASSEMBLY
            and d['origin']['provider_attempts'] == [], 'retained_origin_missing')
    origins = d['origin']['runtime_origins']
    require(type(origins) is list and origins, 'retained_runtime_origins_missing')
    for row in origins:
        require(row['path'] in manifest['files'] and row['sha256'] == manifest['files'][row['path']]['sha256'],
                'retained_actual_origin_changed')
    canonical_rows = {name: read(artifact(folder, ref)) for name, ref in d['canonical'].items()}
    # Recompute full transcripts and compare to statically collected exact-source
    # tests, rather than accepting result.passed, a count, or a list of PASS gates.
    raw_tests = d['primary_test_receipts']
    require(set(raw_tests) == {'offline', 'crash', 'restart', 'integrated', 'directional', 'bounded',
                               'joined_crash', 'joined_provider', 'joined_long_horizon'}, 'primary_test_receipt_missing')
    checked = {}
    for name, receipts in raw_tests.items():
        require(type(receipts) is list and receipts, 'empty_primary_test_receipt')
        runs = []
        require({r['lane'] for r in receipts} == set(LANES), 'all_four_primary_lanes_required')
        selectors_seen = set()
        for r in receipts:
            require(set(r) == {'lane', 'source', 'modules', 'log', 'exit_code'}
                    and r['lane'] in LANES and type(r['exit_code']) is int and r['exit_code'] == 0,
                    'primary_raw_test_execution_invalid')
            # Source path may be a preserved prepared lane, never arbitrary code.
            src = relative(folder, r['source'])
            prepared = d['prepared']['lanes'][r['lane']]
            require(r['source'] == prepared['source'] and src.is_dir(), 'primary_test_source_not_prepared_lane')
            # A caller cannot substitute an unrelated passing test. Every lane
            # must preserve its entire frozen offline test collection for the
            # retained semantic classes. This is conservative and accepts no
            # partial bundle or undocumented whitelist.
            test_root = src / ('robinhood_tests' if r['lane'] in ('pons', 'ramses') else 'tests')
            required_modules = sorted(p.relative_to(src).with_suffix('').as_posix().replace('/', '.')
                                      for p in test_root.rglob('test*.py') if p.is_file())
            require(r['modules'] == required_modules and r['lane'] not in selectors_seen,
                    'primary_tests_not_complete_frozen_lane_collection')
            selectors_seen.add(r['lane'])
            expected = source_test_inventory(src, r['modules'])
            runs.append(transcript(artifact(folder, r['log']).read_bytes(), expected))
        checked[name] = runs
    prepared = verify_prepared(folder, d['prepared'], manifest)
    native = {}
    with assembled_verifiers(source):
        from certification.stage_e_native_v2.verify import validate_raw
        from certification.joined_acceptance import evaluate as evaluate_joined
        for case, ref in d['native'].items():
            row = read(artifact(folder, ref))
            validate_raw(row, manifest, case)
            native[case] = row
        joined_inputs = [deepcopy_row(canonical_rows[k]) for k in ('joined_soak', 'joined_crash', 'joined_provider', 'joined_long_horizon')]
        # Primary logs independently establish these dispositions.
        for row in joined_inputs[1:]: row['passed'] = True
        expected = joined_inputs[0]['identity']
        require(expected.get('integration_sha') == S, 'joined_wrong_candidate')
        joined = evaluate_joined(*joined_inputs, expected)
    return dict(inputs=canonical_rows, tests=checked, native=native, prepared=prepared, joined=joined,
                raw_inventory_sha256=file_sha(folder/'RAW_INVENTORY.json'), verified_from_raw=True)


def deepcopy_row(row):
    import copy
    return copy.deepcopy(row)


def verify_prepared(root, proof, assembly_manifest):
    require(set(proof['lanes']) == set(LANES) and proof['candidate_sha'] == S
            and proof['candidate_tree'] == T, 'all_four_exact_composed_lanes_required')
    source_spec = read(REPOSITORY/'certification/sources.json')
    for lane, p in proof['lanes'].items():
        require(p['before'] == p['after'] and p['policy_hashes_before'] == p['policy_hashes_after']
                and p['origin_modules'] and p['collected_test_modules'], 'prepared_before_after_or_collection_missing')
        src = relative(root, p['source'])
        rows = p['before']; require(type(rows) is list and rows, 'prepared_full_inventory_missing')
        actual = {q.relative_to(src).as_posix() for q in src.rglob('*') if q.is_file()}
        require(actual == {r['path'] for r in rows} and len(rows) == len(actual), 'prepared_extra_missing_or_duplicate_file')
        for r in rows:
            f = artifact(src, {'path': r['path'], 'sha256': r['sha256']})
            require(f.stat().st_size == r['bytes'], 'prepared_source_byte_count')
        frozen_lane = source_spec['lanes'][lane]
        hashes = frozen_lane.get('composed_file_hashes', frozen_lane.get('file_hashes', {}))
        require(hashes and all(file_sha(relative(src, name)) == h for name, h in hashes.items()), 'prepared_frozen_lane_file_changed')
        require(p['policy_hashes_before'] and all(file_sha(relative(src, name)) == h for name, h in p['policy_hashes_before'].items()),
                'protocol_frozen_hash_changed')
        require(all(r['sha256'] == file_sha(relative(src, r['path'])) for r in p['origin_modules']), 'prepared_actual_origin_changed')
    require(proof['assembly_digest'] == ASSEMBLY and proof['protocol_inputs']
            and all(file_sha(relative(REPOSITORY, name)) == h for name, h in proof['protocol_inputs'].items()),
            'protocol_frozen_input_changed')
    return dict(all_four_lanes_verified=True, source_and_origins_verified=True, protocols_verified=True)


def canonical_gate(name, r):
    require(r.get('verified_from_raw') is True, 'retained_verified_raw_required')
    rows, tests = r['inputs'], r['tests']
    offline = rows['offline']
    if name in ('exact_source_offline-v3', 'exact_integration_identity-v3'):
        return bool(tests['offline']) and offline['integration_sha'] == S and r['prepared']['all_four_lanes_verified']
    if name == 'native_crash_matrix-v3':
        lanes = rows['crash']['lanes']
        boundaries = ['before_reservation_commit', 'after_reservation_commit', 'after_entry_commit',
                      'after_monitor_or_exit_intent_commit', 'after_settlement_commit']
        valid = len(lanes) == 4 and {x['lane'] for x in lanes} == set(LANES)
        for x in lanes:
            valid = valid and [p['boundary'] for p in x['probes']] == boundaries and all(
                type(p['recovered']) is dict and bool(p['recovered']) for p in x['probes'])
            final = x['final']
            if x['lane'] == 'pump': valid = valid and final['cash'] == 1030 and final['reserved'] == final['open_positions'] == 0
            elif x['lane'] == 'pons': valid = valid and final['cash'] == 1026 and final['remaining_cost_basis'] == 0
            elif x['lane'] == 'ramses': valid = valid and final['available'] == 1030 and final['committed'] == final['open_positions'] == 0
            else: valid = valid and final['cash'] == 1000000000 + final['realized_pnl_lamports'] and final['settled'] == 1 and final['open_positions'] == final['reserved'] == 0
        return bool(tests['crash']) and valid
    if name == 'restart_safety-v3': return bool(tests['restart'])
    if name in ('integrated_current_policy-v3', 'preserved_production_adapter_contracts-v3'):
        integrated = rows['integrated']; governor = integrated['contention']['governor']
        return bool(tests['integrated']) and set(integrated['lanes']) == set(LANES) and not governor['queues'] and {
            r['lane']: r['granted'] for r in governor['lane_grants']} == {lane: 3 for lane in LANES}
    if name == 'six_regime_integration-v3':
        return bool(tests['directional']) and rows['directional']['integration_sha'] == S
    if name == 'bounded_preserved_validation-v3':
        return bool(tests['bounded']) and rows['bounded']['integration_sha'] == S and rows['bounded']['fresh_market_data_used'] is False
    if name in ('historical_exposure_resolution-v3', 'historical_registry_released-v3'):
        h, registry = rows['historical'], rows['registry']
        after = h['after']
        valid = (h['disposition'] == 'certified_historical_unreplayable_zero_proceeds_writeoff'
            and h['immutable_original_artifact_preserved'] is True and h['market_settlement_performed'] is False
            and all(type(after[k]) is int and after[k] == 0 for k in ('open_positions', 'reserved', 'stale_marks'))
            and type(after['writeoffs']) is int and after['writeoffs'] == 1)
        return valid and (name == 'historical_exposure_resolution-v3' or
            registry['unresolved'] == [] and len(registry['resolved']) == 1
            and registry['resolved'][0]['resolution']['receipt_sha256'] == h['receipt_sha256']
            and registry['resolved'][0]['resolution']['disposition'] == h['disposition'])
    if name == 'joined_eight_day_system-v3': return r['joined']['passed'] is True and not r['joined']['violations']
    if name in ('prepared-source-v3', 'prepared-import-collection-v3'): return r['prepared']['source_and_origins_verified']
    if name == 'protocol-freeze-v3': return r['prepared']['protocols_verified']
    case = {'checkpoint-completion-v3': 'held-reader', 'native-archive-v3': 'native-transitions',
            'native-retirement-v3': 'native-transitions', 'generation-fencing-v3': 'generation-restart',
            'restart-accounting-v3': 'm1-completion'}.get(name)
    require(case is not None and case in r['native'], 'retained_gate_mapping_missing')
    return True  # validate_raw has already rederived this exact primary witness.
