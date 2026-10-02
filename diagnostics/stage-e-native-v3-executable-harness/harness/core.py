"""External v3 identities. Importing this module cannot release source data."""
import hashlib
import json
from pathlib import Path
import time

S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
CONTRACT_COMMIT = '5ed5aef4dfe1bb7823037fe1ce440c193411a194'
CONTRACT_MANIFEST_SHA = '786308bcfc18c88f1c5e97286c311766159d592b47a637d2c6ae6ff53ffd22f0'
ASSEMBLY = '08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659'
ASSEMBLY_MANIFEST_SHA = 'd60d02a32838df4658cc5943d469057ec08ece11e82301b3e85231e029c9eaa0'
ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / 'harness'
CONTRACT = ROOT.parent / 'stage-e-native-v3-production-envelope-contract'
COHORT = (('combined-1', 2223), ('combined-2', 2223), ('combined-3', 2223), ('recovery-1', 4445))
MODES = ('baseline', 'observed', 'observed', 'baseline', 'baseline', 'observed')
REAL_NS = time.monotonic_ns
REAL_MONO = time.monotonic
PERF_NS = time.perf_counter_ns
REAL_UTC_NS = time.time_ns
HEADROOM = 12 * 1024**3
RAM = 8 * 1024**3
MAGIC = b'MMOBSV2\0'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key:' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def relative(root, name):
    root = Path(root).resolve()
    path = root / name
    require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'unsafe_artifact_path')
    require(path.resolve().is_relative_to(root) and not path.is_symlink(), 'artifact_symlink_or_escape')
    return path


def contract_file(name):
    require(file_sha(CONTRACT / 'package_sha256.json') == CONTRACT_MANIFEST_SHA,
            'astra_contract_manifest_changed')
    rows = read(CONTRACT / 'package_sha256.json')['artifacts']
    expected = next((row for row in rows if row['path'] == name), None)
    require(expected is not None and file_sha(relative(CONTRACT, name)) == expected['sha256'],
            'astra_contract_bytes_changed:' + name)
    return read(CONTRACT / name)


def workload(kind):
    names = {'A': 'production_capacity_workload.json', 'B': 'observer_workload.json',
             'C': 'adversarial_stress_workload.json'}
    require(kind in names, 'unknown_execution_class')
    return contract_file(names[kind])


def stopped(reason):
    return dict(paper_only=True, stage_e='RED', stage_f='NOT STARTED',
                execution_authorized=False, source_frames_released=0,
                capacity_executed=False, observer_executed=False, stress_executed=False,
                disposition='STOP FOR ASTRA/OWNER', reason=reason)
