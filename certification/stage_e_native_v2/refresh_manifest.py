"""Explicit offline byte index refresh. Plan never hashes its own manifest.

The plan bytes are an input to the manifest; both exact digests are predeclared
before any trial. Evidence/report/assembly outputs are deliberately external.
"""
from pathlib import Path
import json
from .contract import HERE, ROOT, sha256


def main():
    files={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()) for p in HERE.rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and p.name!='input-manifest-v2.json'}
    for path in (ROOT/'.github/workflows').glob('stagee-native-qualification-v2*.yml'):
        files[path.relative_to(ROOT).as_posix()]=sha256(path.read_bytes())
    # Qualification consumes production modules without editing their bytes.
    # Pin the full local runtime package rather than guessing transitive imports.
    for path in (ROOT/'meme_machine').rglob('*.py'):
        files[path.relative_to(ROOT).as_posix()]=sha256(path.read_bytes())
    for name in ('certification/__init__.py','requirements.txt'):
        path=ROOT/name;files[name]=sha256(path.read_bytes())
    manifest=dict(version='stage-e-successor-input-manifest-v2',schema_version=2,inputs=dict(sorted(files.items())),
        self_hash_policy='manifest SHA-256 bound by external predeclaration; no circular self hash',
        historical_inputs='separate immutable plan.historical_inputs')
    (HERE/'input-manifest-v2.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
