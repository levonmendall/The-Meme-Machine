"""Generate explicitly synthetic protocol-shaped tape, not captured history."""
import json
from pathlib import Path
from tests.support import MINT,SCOUT,event,evidence,snapshot

def main():
    frames=[dict(now=100,events=[event()],evidence={MINT:evidence()}),
            dict(now=102,snapshots={MINT:snapshot(102)}),
            dict(now=107,snapshots={MINT:snapshot(107,sol=65_000_000_000)}),
            dict(now=112,snapshots={MINT:snapshot(112,sol=65_000_000_000)})]
    Path('tests/fixtures/synthetic_lifecycle.jsonl').write_text('\n'.join(json.dumps(x) for x in frames)+'\n')
    config=json.loads(Path('config.synthetic.json').read_text());config['seeds']=[SCOUT]
    Path('config.synthetic.json').write_text(json.dumps(config,indent=2)+'\n')
if __name__=='__main__':main()
