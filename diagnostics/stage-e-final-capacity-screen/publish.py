"""Publish an exact local Git commit via GitHub Git Data, without altering it."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path('/workspace/The-Meme-Machine')
API='repos/levonmendall/The-Meme-Machine/'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def request(method,path,row=None):
    args=['gh','api','--method',method,API+path]
    if row is None:return json.loads(subprocess.check_output(args))
    with tempfile.NamedTemporaryFile(mode='w',dir='/workspace/stage-e-screen-work',suffix='.json') as stream:
        json.dump(row,stream);stream.flush()
        return json.loads(subprocess.check_output(args+['--input',stream.name]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);p.add_argument('--branch',required=True)
    a=p.parse_args();commit=a.commit
    parent=git('rev-parse',commit+'^').decode().strip()
    tree=git('rev-parse',commit+'^{tree}').decode().strip()
    entries=[]
    diff=git('diff-tree','--no-commit-id','--name-status','-r','-z',parent,commit).split(b'\0')
    i=0
    while i<len(diff)-1:
        status,path=diff[i].decode(),diff[i+1].decode();i+=2
        if status=='D':entries.append({'path':path,'mode':'100644','type':'blob','sha':None});continue
        assert status in ('A','M'),status
        mode=git('ls-tree',commit,'--',path).decode().split()[0]
        data=git('show',commit+':'+path)
        blob=request('POST','git/blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})['sha']
        assert blob==git('rev-parse',commit+':'+path).decode().strip(),path
        entries.append({'path':path,'mode':mode,'type':'blob','sha':blob})
    created=request('POST','git/trees',{'base_tree':git('rev-parse',parent+'^{tree}').decode().strip(),'tree':entries})
    assert created['sha']==tree,'remote_tree_mismatch'
    parts=git('show','-s','--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B',commit).decode().split('\0')
    message=parts[6].rstrip('\n')+'\n'
    remote=request('POST','git/commits',{'tree':tree,'parents':[parent],'message':message,
        'author':dict(zip(('name','email','date'),parts[:3])),
        'committer':dict(zip(('name','email','date'),parts[3:6]))})
    assert remote['sha']==commit,('remote_commit_mismatch',remote['sha'],commit)
    try:existing=request('GET','git/ref/heads/'+a.branch)
    except subprocess.CalledProcessError:existing=None
    if existing:
        request('PATCH','git/refs/heads/'+a.branch,{'sha':commit,'force':False})
    else:
        request('POST','git/refs',{'ref':'refs/heads/'+a.branch,'sha':commit})
    reread=request('GET','git/ref/heads/'+a.branch)
    assert reread['object']['sha']==commit
    print(json.dumps({'published_commit':commit,'tree':tree,'branch':a.branch,'remote_ref_read_back':True}))

if __name__=='__main__':main()
