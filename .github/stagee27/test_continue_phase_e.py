"""Offline safety probes for the control-branch driver; never use a real token."""
import base64,copy,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path.cwd().resolve()))
spec=importlib.util.spec_from_file_location('driver',Path(__file__).with_name('continue_phase_e.py'))
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
class API:
 def __init__(self):
  self.calls=[];self.refs={};self.contents={};self.runs=[];self.empty=False;self.lost=False;self.publish=True;self.wrong=False;self.branch=d.SHA;self.active=True
 def request(self,m,p,data=None):
  self.calls.append((m,p,copy.deepcopy(data)))
  if p=='git/ref/heads/'+d.BRANCH:return {'object':{'sha':self.branch}}
  if p=='git/ref/heads/'+d.dispatch.BRANCH:return {'object':{'sha':d.OLD_CANONICAL}}
  if p.startswith('git/ref/'):
   name=p[len('git/ref/'):]
   if name not in self.refs:raise HTTPError('https://example.invalid',404,'missing',{},None)
   return {'object':{'sha':self.refs[name]}}
  if p.startswith('contents/'):
   return {'encoding':'base64','content':base64.b64encode(self.contents[p.split('?ref=')[1]].encode()).decode()}
  if m=='POST' and p=='git/trees':self.pending=data['tree'][0]['content'];return {'sha':'tree'}
  if m=='POST' and p=='git/commits':self.contents['commit']=self.pending;return {'sha':'commit'}
  if m=='POST' and p=='git/refs':
   self.refs[data['ref'][len('refs/'):]]=data['sha'];return {'object':{'sha':data['sha']}}
  if m=='GET' and p.startswith('actions/workflows/') and '/runs?' not in p:
   return {'state':'active' if self.active else 'disabled_manually','path':'.github/workflows/'+p.split('/')[-1]}
  if m=='GET' and '/runs?' in p:return {'total_count':len(self.runs),'workflow_runs':copy.deepcopy(self.runs) if p.endswith('&page=1') else []}
  if m=='POST' and p.endswith('/dispatches'):
   if self.publish:self.runs=[dict(id=99,head_sha='b'*40 if self.wrong else d.SHA,head_branch=d.BRANCH,run_attempt=1,path='.github/workflows/'+p.split('/')[-2],event='workflow_dispatch',status='queued',referenced_workflows=[{'sha':d.SHA}])]
   if self.lost:raise TimeoutError('simulated lost response')
   return None if self.empty else {'workflow_run_id':99}
  if m=='GET' and p=='actions/runs/99':return copy.deepcopy(self.runs[0])
  raise AssertionError((m,p,data))
 def posts(self):return [r for r in self.calls if r[0]=='POST' and r[1].endswith('/dispatches')]
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();d.OUT=Path(self.tmp.name);os.environ['GITHUB_RUN_ID']='77'
 def tearDown(self):self.tmp.cleanup()
 def execute(self,api):return d.dispatch_once(api,'required-full',{'expected_sha':d.SHA},polls=1,sleep=lambda _:None)
 def test_success_receipt_is_bound_and_dispatch_once(self):
  api=API();self.assertEqual(self.execute(api),99);self.assertEqual(self.execute(api),99);self.assertEqual(len(api.posts()),1)
 def test_empty204_and_lost_response_reconcile_get_only(self):
  for flag in ['empty','lost']:
   with self.subTest(flag=flag):
    api=API();setattr(api,flag,True);self.assertEqual(self.execute(api),99);self.assertEqual(len(api.posts()),1)
 def test_missing_response_cannot_be_reposted_from_new_local_directory(self):
  api=API();api.lost=True;api.publish=False
  with self.assertRaisesRegex(RuntimeError,'get_only_no_retry'):self.execute(api)
  with tempfile.TemporaryDirectory() as td:
   d.OUT=Path(td)
   with self.assertRaisesRegex(RuntimeError,'get_only_no_retry'):self.execute(api)
  self.assertEqual(len(api.posts()),1)
 def test_wrong_sha_never_counts_as_success(self):
  api=API();api.wrong=True
  with self.assertRaisesRegex(ValueError,'run_identity_mismatch'):self.execute(api)
  self.assertEqual(len(api.posts()),1)
 def test_branch_move_stops_before_writes(self):
  api=API();api.branch='b'*40
  with self.assertRaisesRegex(ValueError,'branch_moved'):self.execute(api)
  self.assertFalse([r for r in api.calls if r[0]!='GET'])
 def test_unregistered_workflow_stops_before_writes(self):
  api=API();api.active=False
  with self.assertRaisesRegex(ValueError,'not_registered'):self.execute(api)
  self.assertFalse([r for r in api.calls if r[0]!='GET'])
 def test_market_or_unknown_purpose_is_not_authorized(self):
  api=API()
  with self.assertRaisesRegex(ValueError,'not_authorized'):d.dispatch_once(api,'phase-f',{'expected_sha':d.SHA})
  self.assertEqual(api.calls,[])
if __name__=='__main__':unittest.main(verbosity=2)
