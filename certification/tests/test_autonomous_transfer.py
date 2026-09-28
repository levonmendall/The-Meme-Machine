"""Capsule transport uses existing byte proofs across bounded immutable parts."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import zipfile

from certification import autonomous_transfer as transfer, autonomous_window as adapter
from certification import autonomous_control as control, campaign_state
from certification.tests import test_campaign_state as fixtures


class ArtifactAPI:
    def __init__(self):self.items={};self.payloads={};self.downloads=[]
    def publish(self,name,files):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for key,value in files.items():archive.writestr(key,value)
        raw=stream.getvalue()
        item=dict(id=len(self.items)+1,name=name,digest='sha256:'+hashlib.sha256(raw).hexdigest(),workflow_run_id=1)
        self.items[name]=item;self.payloads[name]=raw
        return dict(item)
    def request(self,method,path):
        assert method=='GET' and path.startswith('actions/runs/1/artifacts?')
        return dict(artifacts=list(self.items.values()) if path.endswith('page=1') else [])
    def artifact(self,run_id,name):
        assert run_id==1
        self.downloads.append(name);raw=self.payloads[name];item=self.items[name]
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=item['digest']:raise ValueError('program_artifact_digest')
        return zipfile.ZipFile(io.BytesIO(raw)),dict(item)


def preserve(api,output,destination,claim):
    name=control.artifact_name(claim,1)
    native=api.publish(name+'-native',{str(p.relative_to(output/'artifact')):p.read_bytes() for p in (output/'artifact').rglob('*') if p.is_file()})
    body=transfer.pack(output,destination,claim,native)
    for part in body['parts']:
        api.publish(transfer.part_name(name,part['index']),{'payload':(destination/'parts'/str(part['index']).zfill(2)/'payload').read_bytes()})
    sealed=transfer.seal(api,destination,name)
    reference=api.publish(name,{'transfer.json':(destination/'index/transfer.json').read_bytes()})
    return reference,sealed


class CapsuleTransferTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.CampaignStateTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.root=fixture.root
        fixture.run.rename(self.root/'certification-hourly')
        (self.root/'certification-hourly/result.json').write_text(json.dumps(fixture.terminal))
        adapter.stage(fixture.lanes,self.root,'hourly')
        assurance=self.root/'artifact/assurance';assurance.mkdir();(assurance/'market-assurance.json').write_text('{}')
        (self.root/'smoke-continuation-state.json').write_text('{}')
        review=dict(passed=True,identity=fixture.identity,state_hash=fixture.body['state_hash'])
        (self.root/'window-review.json').write_text(json.dumps(review))
        self.claim=dict(identity=fixture.identity,campaign_id=fixture.window['campaign_id'],
            authorization_hash=fixture.window['authorization_hash'],window=dict(fixture.window,mode='hourly'))
        self.api=ArtifactAPI();self.parts=patch.object(transfer,'PART_BYTES',32768);self.parts.start();self.addCleanup(self.parts.stop)
        self.reference,self.body=preserve(self.api,self.root,self.root/'transfer',self.claim)

    def test_many_parts_restore_exact_capsule_with_one_part_cache_and_no_raw_history_download(self):
        self.assertGreater(len(self.body['parts']),1)
        result=adapter.extract_artifact(self.api,self.reference,self.root/'downloaded')
        for name in self.body['files']:
            self.assertEqual((result/name).read_bytes(),(self.root/name).read_bytes(),name)
        self.assertNotIn(self.body['native_artifact']['name'],self.api.downloads)
        self.assertFalse((result/'artifact/evidence-snapshot.json').exists())
        self.assertEqual(adapter.read(result/'transfer-proof.json')['native_artifact'],self.body['native_artifact'])
        self.assertEqual(campaign_state.verify(result/'capsule',expected_identity=self.fixture.identity,
            expected_state_hash=self.fixture.body['state_hash'],campaign_id=self.claim['campaign_id'],prior_index=0,
            authorization_hash=self.claim['authorization_hash']),self.fixture.body)
        # Temp cache is anonymous and no joined multi-gigabyte ZIP is retained.
        self.assertEqual(sorted(p.name for p in result.iterdir()),['artifact','capsule','smoke-continuation-state.json','transfer-proof.json','window-review.json'])

    def test_missing_or_changed_native_archive_blocks_restore_before_part_download(self):
        self.api.items[self.body['native_artifact']['name']]['digest']='sha256:'+'f'*64
        with self.assertRaisesRegex(ValueError,'native_drift'):
            adapter.extract_artifact(self.api,self.reference,self.root/'bad')
        self.assertEqual(self.api.downloads,[self.reference['name']])

    def test_corrupt_part_and_wrong_preserved_part_identity_reject(self):
        name=self.body['parts'][0]['artifact']['name']
        self.api.payloads[name]=self.api.payloads[name][:-1]+b'!'
        with self.assertRaisesRegex(ValueError,'artifact_digest'):
            adapter.extract_artifact(self.api,self.reference,self.root/'corrupt')
        self.api.publish(name,{'payload':b'wrong bytes'})
        with self.assertRaisesRegex(ValueError,'part_artifact'):
            adapter.extract_artifact(self.api,self.reference,self.root/'wrong')

    def test_manifest_cannot_change_run_order_sizes_authority_or_aggregate_bounds(self):
        cases=[]
        for key,value in [('workflow_run_id',2),('entry_authority',True),('bytes',transfer.TOTAL_BYTES+1)]:
            body=deepcopy(self.body);body[key]=value;cases.append(body)
        body=deepcopy(self.body);body['parts'].reverse();cases.append(body)
        body=deepcopy(self.body);body['parts'][0]['bytes']-=1;cases.append(body)
        body=deepcopy(self.body);body['parts'][0]['artifact']['name']='unrelated';cases.append(body)
        body=deepcopy(self.body);body['parts'][0]['artifact']['workflow_run_id']=2;cases.append(body)
        for body in cases:
            with self.subTest(body=body.get('bytes')),self.assertRaises(ValueError):transfer.validate(body,self.reference)

    def test_verified_outer_part_still_needs_original_inner_bytes_hash(self):
        body=deepcopy(self.body);body['parts'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'part_hash'):
            transfer.extract(self.api,body,self.reference,self.root/'wrong-hash',adapter.extract_checked)

    def test_packing_refuses_corrupt_capsule_or_native_snapshot(self):
        target=next((self.root/'capsule/files').rglob('paper.sqlite'));target.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'campaign_state_file_hash'):
            transfer.pack(self.root,self.root/'bad-pack',self.claim,self.body['native_artifact'])

    def test_missing_part_prevents_publishing_any_successor_index(self):
        folder=self.root/'interrupted';folder.mkdir()
        pending=deepcopy(self.body)
        for part in pending['parts']:part.pop('artifact')
        (folder/'pending.json').write_text(json.dumps(pending))
        del self.api.items[self.body['parts'][-1]['artifact']['name']]
        with self.assertRaisesRegex(ValueError,'artifact_not_preserved'):
            transfer.seal(self.api,folder,self.reference['name'])
        self.assertFalse((folder/'index').exists())

    def test_position_only_transport_preserves_snapshot_without_discovery_assurance(self):
        claim=deepcopy(self.claim);claim['window']['mode']='position'
        positions={lane:dict(position='existing',entry_authority=False) for lane in campaign_state.LANES}
        (self.root/'position-after.json').write_text(json.dumps(positions))
        self.api=ArtifactAPI()
        reference,body=preserve(self.api,self.root,self.root/'position-transfer',claim)
        result=adapter.extract_artifact(self.api,reference,self.root/'position-restored')
        self.assertEqual(adapter.read(result/'position-after.json'),positions)
        self.assertFalse((result/'artifact/assurance/market-assurance.json').exists())
        self.assertFalse(body['entry_authority'])

    def test_part_count_and_total_guards_do_not_expand_with_input(self):
        with patch.object(transfer,'PART_BYTES',32),patch.object(transfer,'TOTAL_BYTES',1024):
            with transfer._Parts(self.root/'bounded') as writer:
                writer.write(b'a'*1024)
                with self.assertRaisesRegex(ValueError,'total_bound'):writer.write(b'x')
            self.assertEqual(len(writer.rows),32)
            self.assertTrue(all(row['bytes']==32 for row in writer.rows))

    def test_workflow_uploads_all_parts_before_index_and_finish_with_fixed_bounds(self):
        workflow=(Path(__file__).parents[2]/'.github/workflows/autonomous-paper.yml').read_text()
        self.assertIn('name: ${{ env.AUTONOMOUS_ARTIFACT_NAME }}-native',workflow)
        for index in range(32):
            self.assertIn('name: ${{ env.AUTONOMOUS_ARTIFACT_NAME }}-part-'+str(index).zfill(2),workflow)
            self.assertIn("inputs.operation == 'window' && fromJSON(steps.pack.outputs.parts) > "+str(index),workflow)
        self.assertLess(workflow.index('autonomous_window seal-transfer'),workflow.index('Preserve exact capsule transfer index'))
        self.assertLess(workflow.index('Preserve exact capsule transfer index'),workflow.index('autonomous_window finish'))
        self.assertEqual(transfer.TOTAL_BYTES,8*1024**3);self.assertEqual(transfer.MAX_PARTS,32)
        self.assertEqual(transfer.MAX_FILES,50000)
