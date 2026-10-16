"""Freeze the reviewed issue #138 source delta; run only after agent edits settle."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.test_robinhood_usd_valuation import RALLY_BASE, RALLY_SCHEMA, rally_delta


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    changed = set(git('diff', '--name-only', RALLY_BASE, '--', 'meme_machine',
        'operational/strategy-change-audit.py', 'tests/test_operational_nine.py').decode().splitlines())
    changed.update(git('ls-files', '--others', '--exclude-standard', '--', 'meme_machine').decode().splitlines())
    changed = sorted(path for path in changed if path.endswith(('.py', '.json')))
    manifest = dict(schema=RALLY_SCHEMA, base=RALLY_BASE, revision='paper-postgrad-rally-v1',
        owner_issue='https://github.com/levonmendall/The-Meme-Machine/issues/138',
        files={}, added_sources={})
    for relative in changed:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit('Missing or nonregular reviewed source: ' + relative)
        after = path.read_bytes()
        before = subprocess.run(['git', 'show', RALLY_BASE + ':' + relative], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if before.returncode:
            manifest['added_sources'][relative] = dict(sha256=hashlib.sha256(after).hexdigest())
            continue
        if before.stdout == after:
            continue
        if path.suffix != '.py':
            raise SystemExit('A changed non-Python source needs its own exact delta guard: ' + relative)
        manifest['files'][relative] = dict(before_sha256=hashlib.sha256(before.stdout).hexdigest(),
            after_sha256=hashlib.sha256(after).hexdigest(), **rally_delta(before.stdout, after))
    if not manifest['files'] or not manifest['added_sources']:
        raise SystemExit('The finalized revision must contain modified and added protected source.')
    target = ROOT / 'tests/fixtures/paper_postgrad_rally_source_delta.json'
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print('Frozen', len(manifest['files']), 'changed sources and', len(manifest['added_sources']), 'added sources.')
    print('Manifest SHA-256:', hashlib.sha256(target.read_bytes()).hexdigest())
    print('Changed source list:', repr(tuple(manifest['files'])))
    print('Added source list:', repr(tuple(manifest['added_sources'])))


if __name__ == '__main__':
    main()
