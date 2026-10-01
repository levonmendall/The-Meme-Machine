"""Plan and byte provenance validation, shared by preflight and every trial."""
import hashlib
import json
from pathlib import Path

from . import CONTRACT, COHORT, HELD_READER, SCHEMA, SCHEMA_VERSION, PLAN

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def strict_json(data):
    def pairs(rows):
        result = {}
        for k, v in rows:
            if k in result:
                raise ValueError('duplicate_json_key:' + k)
            result[k] = v
        return result
    def bad(value):
        raise ValueError('nonfinite_json:' + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad)


def read(path):
    return strict_json(Path(path).read_bytes())


def identities(root=ROOT):
    directory = Path(root) / 'certification/stage_e_native_v2'
    return dict(contract_version=CONTRACT, cohort_version=COHORT,
        held_reader_version=HELD_READER, schema_version=SCHEMA_VERSION,
        evidence_schema=SCHEMA, plan_version=PLAN,
        plan_hash=sha256((directory / 'plan-v2.json').read_bytes()),
        input_manifest_hash=sha256((directory / 'input-manifest-v2.json').read_bytes()),
        gate_map_hash=sha256((directory / 'gate-map-v2.json').read_bytes()))


def checked_path(root, name):
    if not isinstance(name, str) or not name or '\\' in name or '..' in Path(name).parts:
        raise ValueError('invalid_manifest_path')
    p = Path(root) / name
    if Path(name).is_absolute() or p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('manifest_path_escape_or_missing:' + name)
    return p


def validate_inputs(root=ROOT):
    root = Path(root)
    directory = root / 'certification/stage_e_native_v2'
    plan = read(directory / 'plan-v2.json')
    expected = dict(contract_version=CONTRACT, cohort_version=COHORT,
        held_reader_version=HELD_READER, evidence_schema=SCHEMA,
        schema_version=SCHEMA_VERSION, plan_version=PLAN)
    if any(plan.get(k) != v for k, v in expected.items()):
        raise ValueError('v2_plan_identity')
    manifest = read(directory / 'input-manifest-v2.json')
    for name, digest in manifest['inputs'].items():
        if sha256(checked_path(root, name).read_bytes()) != digest:
            raise ValueError('input_hash_mismatch:' + name)
    for name, digest in plan['historical_inputs'].items():
        if sha256(checked_path(root, name).read_bytes()) != digest:
            raise ValueError('historical_input_changed:' + name)
    maps = read(directory / 'gate-map-v2.json')
    if sha256((directory / 'gate-map-v2.json').read_bytes()) != plan['gate_map_hash']:
        raise ValueError('gate_map_hash_mismatch')
    if set(plan['required_gates']) != {r['new_gate'] for r in maps['gates'] if r['required']}:
        raise ValueError('predecessor_gate_dropped')
    if any(r['required'] and r['classification'] == 'UNRESOLVED' for r in maps['gates']):
        raise ValueError('unresolved_required_gate')
    controlled = {p.relative_to(root).as_posix() for p in directory.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.name not in ('input-manifest-v2.json', 'plan-v2.json')}
    controlled |= {'certification/stage_e_native_v2/plan-v2.json'}
    if not controlled <= set(manifest['inputs']):
        raise ValueError('unmanifested_qualification_input')
    return identities(root)
