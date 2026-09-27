"""Missing joined capsule/claim crash cuts, reusing actual eight-day native state."""
import json,os,shutil
from pathlib import Path
from unittest.mock import patch
from certification import campaign_state as state
from certification.autonomous_window import verify_snapshot,checksum
from certification.autonomous_positions import native_proof,live_ids
from certification.market_assurance import native_positions,continuity
from certification.journal import canonical

def run(soak,sources,root):
    root=Path(root);root.mkdir(exist_ok=False)
    source=Path(soak)/'preserved/4';artifact=source/'artifact'
    assert verify_snapshot(artifact)['snapshot_complete']
    capsule=json.loads((source/'capsule/campaign-state.json').read_text());identity=state.identity();assert capsule['identity']==identity
    work=root/'input';run=root/'runtime';shutil.copytree(artifact/'certification-native/hourly',work);shutil.copytree(artifact/'certification-hourly',run)
    sources=Path(sources)
    for lane in state.LANES:
     for name in ('meme_machine','robinhood_research','robinhood_tests','tests'):
      if (sources/lane/name).is_dir():(work/lane/name).symlink_to(sources/lane/name,target_is_directory=True)
    terminal=json.loads((run/'result.json').read_text());window=capsule['window']
    before={lane:native_positions(work/lane,lane) for lane in state.LANES}
    original={str(p.relative_to(artifact)):checksum(p) for p in artifact.rglob('*') if p.is_file()}
    atomic=state._atomic
    calls=[]
    def publication_cut(path,data):
     if path.name=='campaign-state.json':calls.append(str(path));raise SystemExit('joined_before_manifest')
     return atomic(path,data)
    with patch.object(state,'_atomic',side_effect=publication_cut):
     try:state.seal(root/'cut',worktrees=work,run=run,window=window,terminal=terminal,expected_identity=identity,preserved_artifact=artifact)
     except SystemExit:pass
     else:raise AssertionError('missing publication cut')
    assert calls and not (root/'cut/campaign-state.json').exists()
    assert original=={str(p.relative_to(artifact)):checksum(p) for p in artifact.rglob('*') if p.is_file()}
    good=state.seal(root/'capsule',worktrees=work,run=run,window=window,terminal=terminal,expected_identity=identity,preserved_artifact=artifact)
    positions={lane:live_ids(row) for lane,row in before.items()}
    prior=dict(window,state_hash=good['state_hash'],positions=positions,discovery_window=window,artifact={'digest':'sha256:'+'c'*64})
    claim=dict(schema='autonomous-paper-window-claim-v1',identity=identity,campaign_id=window['campaign_id'],authorization_hash=window['authorization_hash'],certificate=dict(identity,passed=True),previous=prior,
     window=dict(index=5,workflow_run_id=6,native_run_id='joined',mode='hourly',seconds=3600,entry_authority=True,nonce='c'*32,parent_state_hash=good['state_hash'],positions=positions))
    real_replace=state.os.replace;installed=[]
    def install_cut(a,b):
     real_replace(a,b);installed.append(str(b))
     if len(installed)==3:raise SystemExit('joined_restore_mid_install')
    with patch.object(state.os,'replace',side_effect=install_cut):
     try:state.prepare_window(claim,worktrees=root/'restored',run=root/'restored-runtime',phase='hourly',seconds=3600,prior_state=root/'capsule')
     except SystemExit:pass
     else:raise AssertionError('missing install cut')
    assert not (root/'restored-runtime/restored-campaign-state.json').exists()
    def claim_cut(path,data):
     if path.name=='autonomous-window-claim.json':raise SystemExit('joined_before_claim')
     return atomic(path,data)
    with patch.object(state,'_atomic',side_effect=claim_cut):
     try:state.prepare_window(claim,worktrees=root/'restored',run=root/'restored-runtime',phase='hourly',seconds=3600,prior_state=root/'capsule')
     except SystemExit:pass
     else:raise AssertionError('missing claim cut')
    assert (root/'restored-runtime/restored-campaign-state.json').exists()
    assert not (root/'restored-runtime/autonomous-window-claim.json').exists()
    state.prepare_window(claim,worktrees=root/'restored',run=root/'restored-runtime',phase='hourly',seconds=3600,prior_state=root/'capsule')
    for lane in state.LANES:
     p=native_proof(lane,root/'restored'/lane,sources/lane);assert p['accounting']==good['accounting'][lane]['accounting'],lane
     after=native_positions(root/'restored'/lane,lane);assert continuity(before[lane],after)['status']=='pass'
     assert after['natural_entries']==before[lane]['natural_entries'];assert not after['violations']
     # No live economic or controller projection changes across either cut.
     for lifecycle_id in positions[lane]:assert after['positions'][lifecycle_id]==before[lane]['positions'][lifecycle_id]
    bad=root/'corrupt';shutil.copytree(root/'capsule',bad)
    (bad/'files'/good['files'][0]['path']).write_bytes(b'corrupt')
    try:state.restore(bad,worktrees=root/'forbidden',run=root/'forbidden-runtime',expected_identity=identity,expected_state_hash=good['state_hash'],campaign_id=window['campaign_id'],prior_index=4,authorization_hash=window['authorization_hash'])
    except ValueError as exc:assert str(exc)=='campaign_state_file_hash',str(exc)
    else:raise AssertionError('corrupt joined capsule restored')
    result=dict(schema='joined-campaign-crash-matrix-v1',passed=True,identity=capsule['identity'],cuts=['after_all_native_compactions_before_capsule_manifest','during_file_install','after_receipt_before_entry_claim','corrupt_capsule'],
     preserved_raw_unchanged=True,restored_entries_unchanged=True,live_positions_exact=True,accounting_exact=True,paper_only=True)
    (root/'result.json').write_text(canonical(result));return result
