"""Hash bounded evidence and publish an Actions summary; never executes workloads."""
import argparse, hashlib, json, os
from pathlib import Path

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',required=True); a=p.parse_args()
    root=Path(a.root); root.mkdir(parents=True,exist_ok=True)
    paths=list(root.glob('*/summary.json'))+list(root.glob('captured/*/variant/summary.json'))
    rows=[json.loads(p.read_text()) for p in paths]
    lines=['# Fresh Stage-E diagnosis','',
        'PAPER ONLY. Stage E RED. Stage F NOT STARTED. No production repair.','',
        '| ID | committed frames | source seconds | refusal/result | observer/debug fraction |',
        '| --- | ---: | ---: | --- | ---: |']
    for r in rows:
        lines.append('| {} | {} | {:.2f} | {} | {:.4%} |'.format(
            r['variant'],r['completed_frames'],r['source_seconds'],r['failure'] or 'horizon completed',
            r['diagnostic_overhead_fraction']))
    lines+=['','The reported wrapper component times measured numeric bookkeeping; entry/return',
        'trampolines and extra clock calls are not fully captured. No <1% qualification claim.',
        'Stage/transaction/owner/worker intervals overlap; they must not be added as independent cost.']
    gate=root/'ASTRA_GATE.json'
    if gate.exists():
        lines+=['',json.loads(gate.read_text())['status'],
            'Workload execution stopped. This publication runs zero diagnostic workloads.',
            'See ASTRA_REVIEW_PACKAGE.md and PUBLICATION_IDENTITY.json.']
    body='\n'.join(lines)+'\n'
    (root/'SUMMARY.md').write_text(body)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream: stream.write(body)
    files={}
    for file in root.rglob('*'):
        if file.is_file() and 'runtime' not in file.relative_to(root).parts and file.name!='SHA256.json':
            files[str(file.relative_to(root))]=hashlib.sha256(file.read_bytes()).hexdigest()
    (root/'SHA256.json').write_text(json.dumps(files,indent=2)+'\n')
    print('EVIDENCE_HASHES '+json.dumps(files,sort_keys=True),flush=True)

if __name__=='__main__': main()
