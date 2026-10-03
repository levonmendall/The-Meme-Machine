"""Independently hash bytes fetched from the published immutable Git commit."""
import ast
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

R=Path(__file__).resolve().parent
G=Path('/workspace/stage-e-source')
C='1a376c7c9f52d70ecdb59247e7bfe779f1c69fbb'
E='diagnostics/stage-e-native-v3-failed-mix-reconciliation-20261003T153000Z'
H='diagnostics/stage-e-native-v3-executable-harness'
EXPECTED='c6d2ea2275b68dc1dc650e53b76a98ddc46b71d2f12d9a4d60c6c603e97bdd7f'
DEST=R/'independent-publication-readback'
DEST.mkdir(exist_ok=True)

def sha(b):return hashlib.sha256(b).hexdigest()

archive=subprocess.check_output(['git','archive',C,E+'/published',H,'.github/workflows/stagee-native-v3-executable-review.yml','diagnostics/stage-e-native-v3-production-envelope-contract'],cwd=G)
with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(DEST,filter='data')
P=DEST/E/'published'
manifest=(P/'MANIFEST.json').read_bytes()
assert sha(manifest)==EXPECTED
doc=json.loads(manifest)
mismatches=[]
for f in doc['artifacts']:
    b=(P/f['path']).read_bytes()
    if len(b)!=f['bytes'] or sha(b)!=f['sha256']:mismatches.append(f['path'])
actual={f.relative_to(P).as_posix() for f in P.rglob('*') if f.is_file() and f != P/'MANIFEST.json'}
assert actual=={x['path'] for x in doc['artifacts']}
assert not mismatches
hmanifest=(DEST/H/'package-manifest.json').read_bytes()
assert sha(hmanifest)=='91753a805cd7acd48a10bb5e9cf31673f54ab9aebd70ee89039f37a7606ba9ff'
formal=json.loads(hmanifest)
for f in formal['artifacts']:
    b=(DEST/f['path']).read_bytes()
    assert len(b)==f['bytes'] and sha(b)==f['sha256'],f['path']
    if f.get('mode')=='100755':assert (DEST/f['path']).stat().st_mode & 0o111
    else:assert not ((DEST/f['path']).stat().st_mode & 0o111)

check=subprocess.run(['python',str(DEST/H/'review.py'),'verify-package'],cwd=DEST,capture_output=True,text=True)
assert check.returncode==0,check.stderr
cli=json.loads(check.stdout)
assert cli['verified_artifacts']==65

baseline=subprocess.check_output(['git','show','f480c6b4f7a8442fd148c7ed61bcc4447edaefca:'+H+'/harness/tape.py'],cwd=G)
after=ast.parse((DEST/H/'harness/tape.py').read_bytes())
before=ast.parse(baseline)
old=next(n for n in ast.walk(before) if isinstance(n,ast.Constant) and n.value==256)
new=[n for n in ast.walk(after) if isinstance(n,ast.Constant) and n.value==284]
assert len(new)==1
new[0].value=256
assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)

changed=subprocess.check_output(['git','diff','--name-only','f480c6b4f7a8442fd148c7ed61bcc4447edaefca',C],cwd=G,text=True).splitlines()
assert all(p.startswith(E+'/') or p.startswith(H+'/') or p=='.github/workflows/stagee-native-v3-failed-mix-validation.yml' for p in changed)
assert not any(p.startswith('diagnostics/stage-e-native-v3-production-envelope-contract/') for p in changed)
candidate_tree=subprocess.check_output(['git','rev-parse','7a516a6a92be9347661ac0e7f560971c171a0931^{tree}'],cwd=G,text=True).strip()
assert candidate_tree=='9da7d1e1625ba04c1437c63606c90f5e293bdba7'
receipt=dict(verification_utc=dt.datetime.now(dt.timezone.utc).isoformat(),method='Independent git fetch from GitHub, immutable git archive extraction, independent hashlib SHA-256 and byte-count verification, unchanged approved review.py verify-package; no source-output copy substituted.',published_payload_commit=C,published_repository_tree=subprocess.check_output(['git','rev-parse',C+'^{tree}'],cwd=G,text=True).strip(),evidence_manifest_sha256=sha(manifest),evidence_artifacts_verified=len(doc['artifacts']),evidence_payload_bytes=sum(x['bytes'] for x in doc['artifacts']),evidence_mismatches=mismatches,formal_successor_manifest_sha256=sha(hmanifest),formal_successor_artifacts_verified=len(formal['artifacts']),formal_successor_cli_verification=cli,formal_successor_mode_verification=True,executable_AST_only_256_to_284=True,production_candidate_and_contract_unchanged=True,changed_paths=changed,independent_external_executable_approval=False,Stage_A_admitted=False,A_trials_started=0,A_slots_consumed=0,source_frames_released=0)
(R/'MANIFEST_INDEPENDENT_VERIFICATION.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:receipt[k] for k in ['published_payload_commit','evidence_manifest_sha256','evidence_artifacts_verified','evidence_mismatches','formal_successor_artifacts_verified','executable_AST_only_256_to_284']}))
