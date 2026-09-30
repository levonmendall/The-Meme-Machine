"""Publish already captured fresh evidence after Astra STOP. No workloads or SQLite."""
import argparse, hashlib, io, json, os, platform, subprocess, urllib.request, zipfile
from pathlib import Path

BASE = 'dc08f9064cf5e37b63f383f52aa709d0afc1723f'
PREFIX = 'diagnostics/stage-e-fresh-causal-isolation'
ROOT = Path(__file__).resolve().parents[2]
REPO = 'levonmendall/The-Meme-Machine'

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Signed artifact storage URLs must not receive the repository token.
        return urllib.request.Request(newurl, headers={'Accept':'application/vnd.github+json'})

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def manifest(ref):
    return {s.split('\t', 1)[1]: s.split('\t', 1)[0]
            for s in git('ls-tree', '-r', ref).splitlines()}

def publish(root):
    gate = json.loads((ROOT/PREFIX/'ASTRA_GATE.json').read_text())
    request = json.loads((ROOT/PREFIX/'execution-request.json').read_text())
    assert gate['stop_all_diagnostic_execution'] is True
    assert request['package_only'] is True and request['variants'] == []
    assert gate['material_variants_consumed'] == request['material_variants_consumed'] == 2
    old, new = manifest(BASE), manifest('HEAD')
    assert all(new.get(p) == value for p, value in old.items()), 'production_changed'
    assert all(p.startswith(PREFIX+'/') or p == '.github/workflows/stage-e-fresh-causal-isolation.yml'
               for p in set(new)-set(old)), 'unexpected_added_path'
    identity = dict(source_sha=BASE, source_tree=git('rev-parse', BASE+'^{tree}'),
        publication_sha=git('rev-parse', 'HEAD'), publication_tree=git('rev-parse', 'HEAD^{tree}'),
        preexisting_files_verified=len(old), all_preexisting_blobs_and_modes_unchanged=True,
        workflow_run_id=os.environ.get('GITHUB_RUN_ID'), run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
        package_only=True, workloads_executed=0, material_variants_consumed=2,
        publishing_environment=dict(os=platform.platform(), python=platform.python_version(),
            cpu_count=os.cpu_count(), purpose='stdlib packaging; not a runtime-equivalence receipt'))
    (root/'PUBLICATION_IDENTITY.json').write_text(json.dumps(identity, indent=2)+'\n')
    print('PUBLICATION_IDENTITY '+json.dumps(identity), flush=True)
    for label in ('M1', 'M2'):
        binding = json.loads((ROOT/PREFIX/(label+'_ARTIFACT.json')).read_text())
        url = 'https://api.github.com/repos/'+REPO+'/actions/artifacts/'+str(binding['id'])+'/zip'
        req = urllib.request.Request(url, headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
            'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.build_opener(SafeRedirect()).open(req, timeout=60) as response:
            raw = response.read(2*1024*1024+1)
        assert len(raw) <= 2*1024*1024
        assert hashlib.sha256(raw).hexdigest() == binding['zip_sha256'], label+'_zip_hash'
        z = zipfile.ZipFile(io.BytesIO(raw))
        assert sum(info.file_size for info in z.infolist()) < 32*1024*1024
        files = {info.filename:z.read(info) for info in z.infolist() if not info.is_dir()}
        hashes = json.loads(files['SHA256.json'])
        assert all(hashlib.sha256(files[name]).hexdigest() == value for name,value in hashes.items())
        summary = json.loads(files['variant/summary.json'])
        assert summary['production_identity']['source_sha'] == BASE
        assert summary['production_identity']['diagnostic_sha'] == binding['head_sha']
        output = root/'captured'/label
        for name, value in files.items():
            parts = Path(name).parts
            assert not Path(name).is_absolute() and '..' not in parts and 'runtime' not in parts
            dest = output/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(value)
        print('PACKAGED_ARTIFACT '+json.dumps(dict(label=label,id=binding['id'],
            zip_sha256=binding['zip_sha256'],files=len(files),manifest_verified=True)), flush=True)
        if label == 'M2':
            rows = [json.loads(line) for line in files['variant/timeline.jsonl'].decode().splitlines()]
            window = [r for r in rows if 210 <= r['elapsed'] <= 301]
            validity = dict(sample_count=len(rows), window_210_301_samples=len(window),
                invalid_window_samples=[dict(elapsed=r['elapsed'],pins=r['pins'],gaps=r['gaps'])
                    for r in window if not r['arrival_inference_valid']],
                final_disconnect_gaps=summary['counters'].get('gaps_created'),
                source='hash-verified existing M2 artifact; no fresh workload')
            print('PACKAGED_M2_VALIDITY '+json.dumps(validity), flush=True)
            selected = []
            for r in rows:
                scheduling = r.get('scheduling') or {}
                obs = r.get('owner_observation') or {}
                selected.append(dict(elapsed=r['elapsed'],frames=r['frames'],
                    source_seconds=r['source_seconds'],source_lag=r['source_lag'],
                    wal_bytes=r['wal_bytes'],pins=r['pins'],gaps=r['gaps'],
                    arrival_inference_valid=r['arrival_inference_valid'],scopes=r['scopes'],
                    owner_observation=dict(monotonic=obs.get('monotonic'),wall=obs.get('wall'),scopes=obs.get('scopes')),
                    owner={k:v for k,v in r['owner'].items() if k in ('queued','queue_peak',
                        'priority2.execution_total_us','priority4.execution_total_us',
                        'priority4.queue_total_us','priority4.completed','checkpoint_handoff_total_us')},
                    scheduling={k:v for k,v in scheduling.items()
                        if k in ('at','ready','selected','feasible','needs','owner_delay',
                                 'worker_age','error','committed_frame','source_coordinate')},
                    cumulative_metrics={k:v for k,v in r['metrics'].items()
                        if k in ('source_owner_native','source_owner_injected_wait',
                                 'archive_worker.native','archive_worker.injected_wait',
                                 'archive_worker.dispatch_to_start','archive_worker.return_transport',
                                 'source_worker.native','source_worker.dispatch_to_start',
                                 'checkpoint_passive_native','checkpoint_boundary_native')}))
            (root/'M2_TIMELINE.json').write_text(json.dumps(selected,indent=2)+'\n')
            (root/'M2_OBSERVER_VALIDITY.json').write_text(json.dumps(validity,indent=2)+'\n')
            print('PACKAGED_M2_TIMELINE '+json.dumps(selected,separators=(',',':')), flush=True)
            assert not validity['invalid_window_samples'], 'arrival_inference_invalid'
    print('ASTRA_STOP_ENFORCED: packaging only; zero diagnostic executions', flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    root=Path(a.root);root.mkdir(parents=True,exist_ok=True);publish(root)

if __name__ == '__main__': main()
