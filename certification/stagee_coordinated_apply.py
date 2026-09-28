"""One-shot, exact-predecessor authoring of the coordinated Stage E repair.

This is an offline source-editing tool, not a runtime monkey patch. Every edited
predecessor blob is checked first, and the resulting source is committed before
any certificate is attempted. No strategy, provider, or market workflow is run.
"""
import ast
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'meme_machine/solana_evidence_plane.py': 'd94527e09f889baa647ced4b2658dddd74c0abf7',
    'meme_machine/solana_evidence_control.py': 'd20ba1492789e0f3612efb60007807fdf44104fa',
    'meme_machine/solana_evidence_service.py': 'e7da172fccd1cd6a10c55dffd36a30d14154b305',
    '.github/workflows/non-market-certification.yml': '3ca92d701112bcf90fe1bd5dd13e613baecd3267',
    'certification/final_acceptance.py': '8c0814b8a69fdec3a318a96073bfe62b50d78614',
    'certification/tests/test_final_acceptance.py': '02d4e79a869c8804cceebeceb14c79eba9673a2d',
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('coordinated_source_anchor:' + old[:80])
    return text.replace(old, new, 1)


def apply():
    content = {}
    for name, expected in EXPECTED.items():
        path = ROOT/name
        actual = subprocess.check_output(['git', 'hash-object', str(path)], text=True).strip()
        if actual != expected:
            raise ValueError('coordinated_predecessor_blob_drift:' + name)
        content[name] = path.read_text()

    name = 'meme_machine/solana_evidence_plane.py'
    text = content[name]; module = ast.parse(text)
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'EvidenceWriter')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'archive_snapshot')
    lines = text.splitlines(keepends=True)
    replacement = ('    def archive_snapshot(self,before_time,*,max_records=1000,max_bytes=4*1024*1024):\n'
                   '        """Copy the exact bounded archive input using set-based metadata reads."""\n'
                   '        from .solana_archive_snapshot import snapshot\n'
                   '        return snapshot(self,before_time,max_records=max_records,max_bytes=max_bytes)\n')
    content[name] = ''.join(lines[:method.lineno-1]) + replacement + ''.join(lines[method.end_lineno:])

    name = 'meme_machine/solana_evidence_control.py'; text = content[name]
    text = replace_once(text,
        '        self.closed=False; self.ready=concurrent.futures.Future()\n',
        '        self.closed=False; self.ready=concurrent.futures.Future()\n'
        '        self._checkpoint_epoch=0; self._checkpoint_busy=False\n')
    text = replace_once(text,
        "                    self.metrics[prefix+'.queue_total_us']=self.metrics.get(prefix+'.queue_total_us',0)+wait\n",
        "                    self.metrics[prefix+'.queue_total_us']=self.metrics.get(prefix+'.queue_total_us',0)+wait\n"
        '                    self._checkpoint_busy=True\n')
    text = replace_once(text,
        '                    with self.cv:\n                        if interrupted:',
        '                    with self.cv:\n'
        '                        self._checkpoint_epoch+=1; self._checkpoint_busy=False\n'
        '                        if interrupted:')
    text = replace_once(text, '    def telemetry(self):\n',
        '    def checkpoint_ticket(self):\n'
        '        """Conservative owner-generation fence, never database authority."""\n'
        '        with self.cv:\n'
        '            if self.closed or self.queue or self._checkpoint_busy:return None\n'
        '            return self._checkpoint_epoch\n\n'
        '    def checkpoint_current(self,ticket):\n'
        '        # Called inside the admitted owner callback. Any intervening\n'
        '        # operation, including a command outside serve.work(), invalidates\n'
        '        # the old PASSIVE completion. Reads conservatively invalidate too.\n'
        '        with self.cv:\n'
        '            return (type(ticket) is int and not self.closed\n'
        '                    and self._checkpoint_busy and ticket==self._checkpoint_epoch)\n\n'
        '    def telemetry(self):\n')
    content[name] = text

    name = 'meme_machine/solana_evidence_service.py'; text = content[name]
    text = replace_once(text,
        '                pending=asyncio.create_task(asyncio.to_thread(EvidenceWriter.checkpoint,path))\n',
        '                ticket=owner.checkpoint_ticket()\n'
        '                pending=asyncio.create_task(asyncio.to_thread(EvidenceWriter.checkpoint,path))\n')
    old = "                        final=await work(lambda state:state.writer.finish_checkpoint(),2,label='checkpoint_finish')\n"
    new = ("                        def finish_if_current(state):\n"
           "                            if not owner.checkpoint_current(ticket):return None\n"
           "                            return state.writer.finish_checkpoint()\n"
           "                        final=await work(finish_if_current,2,label='checkpoint_finish')\n"
           "                        if final is None:\n"
           "                            counts['checkpoint.tail_deferred']=counts.get('checkpoint.tail_deferred',0)+1\n"
           "                            final=(1,result[1],result[2])\n")
    text = replace_once(text, old, new)
    text = replace_once(text,
        '                # Expensive page copying remains off the sole SQLite owner.\n',
        '                # A generation fence additionally refuses TRUNCATE after\n'
        '                # any intervening owner operation. busy_timeout=0 alone\n'
        '                # limits lock waiting, not the cost of copying a new tail.\n'
        '                # Deferred tails remain for the next independent PASSIVE.\n')
    content[name] = text

    name = '.github/workflows/non-market-certification.yml'; text = content[name]
    text = text.replace('    timeout-minutes: 30\n', '    timeout-minutes: 45\n', 1)
    preparation = '      - run: python -m certification.run prepare --worktrees "$RUNNER_TEMP/non-market-lanes"\n'
    if text.count(preparation) != 2:
        raise ValueError('coordinated_preflight_workflow_shape')
    text = text.replace(preparation, preparation +
        '      - name: Verify complete build identity before expensive gates\n'
        '        run: >-\n'
        '          python -m certification.build_consistency verify\n'
        '          --worktrees "$RUNNER_TEMP/non-market-lanes"\n'
        '          --expected-sha "$GITHUB_SHA"\n'
        '          --output non-market-evidence/build-preflight.json\n')
    text = replace_once(text,
        '      - name: Joined eight-day PAPER campaign and recovery/provider gates\n',
        '      - name: Combined mature source backlog reader checkpoint and control pressure\n'
        '        timeout-minutes: 15\n'
        '        run: |\n'
        '          python -m certification.combined_pressure --output non-market-evidence/combined-pressure > non-market-evidence/combined-pressure.log 2>&1\n'
        '      - name: Joined eight-day PAPER campaign and recovery/provider gates\n')
    content[name] = text

    name = 'certification/final_acceptance.py'; text = content[name]
    text = replace_once(text, "    joined_path=root/'joined/result.json'\n",
        "    from certification.combined_pressure import verified as combined_verified\n"
        "    combined_path=root/'combined-pressure/result.json'\n"
        "    combined=load(combined_path) if combined_path.exists() else {}\n"
        "    combined_pass=combined_verified(combined,offline.get('integration_sha'))\n"
        "    joined_path=root/'joined/result.json'\n")
    text = replace_once(text, '        "mature_solana_pressure":pressure_pass,\n',
        '        "mature_solana_pressure":pressure_pass,\n'
        '        "combined_mature_solana_pressure":combined_pass,\n')
    text = replace_once(text, '        mature_solana_pressure=pressure,\n',
        '        mature_solana_pressure=pressure,\n'
        '        combined_mature_solana_pressure=combined,\n')
    content[name] = text

    name = 'certification/tests/test_final_acceptance.py'; text = content[name]
    anchor = '    def test_missing_short_failed_or_wrong_sha_joined_proof_cannot_certify(self):\n'
    addition = (
        "        from certification.tests.test_combined_pressure import valid_report\n"
        "        (root/'combined-pressure').mkdir()\n"
        "        (root/'combined-pressure/result.json').write_text(json.dumps(valid_report('sha')))\n\n")
    text = replace_once(text, anchor, addition + anchor)
    content[name] = text

    # Only runtime/test overlays are extended; every economic field stays intact.
    sources = json.loads((ROOT/'certification/sources.json').read_text())
    for lane in ('pump', 'meteora'):
        for name in ('meme_machine/solana_archive_snapshot.py', 'tests/test_coordinated_database.py'):
            if name not in sources['lanes'][lane]['integration_overlay_files']:
                sources['lanes'][lane]['integration_overlay_files'].append(name)
    for name, text in content.items():
        if name.endswith('.py'):
            ast.parse(text, filename=name)
    for name, text in content.items():
        (ROOT/name).write_text(text)
    (ROOT/'certification/sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    print(json.dumps(dict(edited=sorted(content), policies_changed=False, paper_only=True)))


if __name__ == '__main__':
    apply()
