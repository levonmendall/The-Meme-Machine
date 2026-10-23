"""Stage a complete owner-throughput source successor after runtime freeze.

This builder imports no application or test modules. Root supplies the exact
combined runtime commit and runs it after review. No default checkout writes,
tests, provider calls, deployment or operational authority are supplied here.
"""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE='44c4d556f9d7eb6f0481cbdceabc4c58e8714e65'
BASE_TREE='c473027bb26189c54cba8cb853d7f741efd5728f'
CAPACITY_BASE='83c3716aefc21d59780db64beb8681e772ac628c'
CAPACITY_IMPLEMENTATION='58daaa5afef66169062b74ffe617cfeaa9975c12'
GUARD='tests/test_managed_capacity_source_guard.py'
GUARD_SHA256='20f4715b8cfa09a268ab6189d7091df09ebb75cb790cbf2fe3832d9b0333d094'
PROTECTED=(
    'tests/fixtures/managed_capacity_source_delta.json',
    'engineering/diagnostics/build_managed_capacity_source_proof.py',
    'engineering/diagnostics/managed_capacity_source_guard.template.txt',
    'tests/test_native_audit_source_guard.py',
    'tests/test_ea_performance_source_guard.py',
    'tests/test_operational_candidate_source_guard.py',
    'tests/test_pump_restore_source_guard.py',
    'tests/test_robinhood_usd_valuation.py',
    'tests/fixtures/native_audit_source_delta.json',
    'tests/fixtures/ea_performance_source_delta.json',
    'tests/fixtures/operational_candidate_source_delta.json',
    'tests/fixtures/pump_restore_reference_source_delta.json',
    'engineering/diagnostics/build_native_audit_source_proof.py',
    'engineering/diagnostics/native_audit_source_guard.template.txt',
    'engineering/diagnostics/build_ea_performance_source_proof.py',
    'engineering/diagnostics/build_operational_candidate_source_proof.py',
    'engineering/diagnostics/operational_candidate_source_guard.template.txt',
    'meme_machine/operational/managed_native_pump.py',
)
NEW_GUARD='tests/test_owner_throughput_source_guard.py'
NEW_MANIFEST='tests/fixtures/owner_throughput_source_delta.json'
NEW_BUILDER='engineering/diagnostics/build_owner_throughput_source_proof.py'
NEW_TEMPLATE='engineering/diagnostics/owner_throughput_source_guard.template.txt'
TEMPLATE=Path(__file__).with_name('owner_throughput_source_guard.template.txt')
IMPORT=('from tests.test_owner_throughput_source_guard import '
    '(throughput_predecessor, throughput_active_delta, throughput_native_delta)\n')


def git(repo,*args):
    return subprocess.check_output(['git','--no-optional-locks',*args],cwd=repo)


def checksum(raw):return hashlib.sha256(raw).hexdigest()


def nodes(raw):
    """Whole functions, class layout/nonmethods and every module statement."""
    found={}
    def walk(parent,prefix=''):
        for index,node in enumerate(parent.body):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                name=prefix+node.name
                if isinstance(node,ast.ClassDef):
                    found[name+'.__layout__']=ast.dump(ast.ClassDef(name=node.name,
                        bases=node.bases,keywords=node.keywords,
                        body=[ast.Pass() if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                            else n for n in node.body],decorator_list=node.decorator_list,
                        type_params=node.type_params))
                    walk(node,name+'.')
                else:found[name]=ast.dump(node)
            else:found[prefix+'__statement_%d'%index]=ast.dump(node)
    walk(ast.parse(raw))
    return found


def imports(raw):
    return sorted(ast.dump(node) for node in ast.walk(ast.parse(raw))
        if isinstance(node,(ast.Import,ast.ImportFrom)))


def record(before,after,status,path):
    row=dict(status=status,after_bytes=len(after),after_sha256=checksum(after))
    if before is not None:row.update(before_bytes=len(before),before_sha256=checksum(before))
    if path.endswith('.py'):
        left={} if before is None else nodes(before);right=nodes(after)
        row.update(changed_nodes=sorted(k for k in left.keys()|right.keys() if left.get(k)!=right.get(k)),
            imports=imports(after))
    return row


def inverse_record(before,after):
    changes=[]
    left,right=before.decode().splitlines(keepends=True),after.decode().splitlines(keepends=True)
    for group in difflib.SequenceMatcher(None,left,right,autojunk=False).get_grouped_opcodes(5):
        first,last=group[0],group[-1]
        prior=''.join(left[first[1]:last[2]]);current=''.join(right[first[3]:last[4]])
        if not current or after.count(current.encode())!=1:
            raise ValueError('unique_complete_guard_inverse_required')
        changes.append(dict(before=prior,after=current))
    restored=after
    for change in reversed(changes):
        a,b=change['before'].encode(),change['after'].encode()
        if restored.count(b)!=1:raise ValueError('unique_guard_hunk_required')
        restored=restored.replace(b,a,1)
    if restored!=before:raise ValueError('whole_original_guard_bytes_required')
    return dict(record(before,after,'M',GUARD),changes=changes)


def rewrite_guard(raw):
    """Only fresh reads, exact delta dispatch and the one predecessor entry."""
    if checksum(raw)!=GUARD_SHA256:raise ValueError('exact_44_original_guard_required')
    tree=ast.parse(raw);lines=raw.splitlines(keepends=True);starts=[];position=0
    for line in lines:starts.append(position);position+=len(line)
    def span(node):
        return starts[node.lineno-1]+node.col_offset,starts[node.end_lineno-1]+node.end_col_offset
    owners={}
    def walk(node,owner=None):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):owner=node
        owners[id(node)]=owner
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(tree)
    edits=[]
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and node.func.attr=='read_bytes' and not node.args and not node.keywords
                and isinstance(node.func.value,ast.BinOp) and isinstance(node.func.value.op,ast.Div)
                and isinstance(node.func.value.left,ast.Name) and node.func.value.left.id=='ROOT'):
            owner=owners[id(node)];argument=owner.args.args[0].arg
            if argument not in ('test','self'):raise ValueError('exact_test_read_owner_required')
            start,end=span(node);pstart,pend=span(node.func.value.right)
            replacement=(b'throughput_predecessor('+argument.encode()+b','+raw[pstart:pend]+b','+
                raw[start:end]+b',require_current=True)')
            edits.append((start,end,replacement))
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    for name,statement in (
        ('capacity_predecessor',b'    current=throughput_predecessor(test,path,current)\n'),
        ('capacity_active_delta',b'    actual=throughput_active_delta(test,actual,old_implementation)\n'),
        ('capacity_native_delta',b'    actual=throughput_native_delta(test,actual,old_implementation)\n')):
        fn=functions[name]
        if name=='capacity_predecessor':offset=starts[fn.body[0].lineno-1]
        else:
            if ast.dump(fn.body[0])!=ast.dump(ast.parse('active_runtime(test)').body[0]):
                raise ValueError('original_complete_active_check_required')
            offset=starts[fn.body[0].end_lineno]
        edits.append((offset,offset,statement))
    current_query=ast.dump(ast.parse("git('diff','--name-only',IMPLEMENTATION,'--','meme_machine')",mode='eval').body)
    candidates=[node for node in ast.walk(functions['active_runtime'])
        if isinstance(node,ast.Call) and ast.dump(node)==current_query]
    if len(candidates)!=1:raise ValueError('single_original_working_runtime_census_required')
    start,end=span(candidates[0]);edits.append((start,end,
        b'throughput_active_delta(test,'+raw[start:end]+b',IMPLEMENTATION)'))
    doc=tree.body[0]
    if not(isinstance(doc,ast.Expr) and isinstance(doc.value,ast.Constant) and isinstance(doc.value.value,str)):
        raise ValueError('original_module_docstring_required')
    offset=sum(len(line) for line in lines[:doc.end_lineno]);edits.append((offset,offset,IMPORT.encode()))
    previous=-1
    for start,end,_ in sorted(edits):
        if start<previous:raise ValueError('nonoverlapping_narrow_hooks_required')
        previous=end
    updated=raw
    for start,end,body in sorted(edits,reverse=True):updated=updated[:start]+body+updated[end:]
    class Strip(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            return None if node.module=='tests.test_owner_throughput_source_guard' else node
        def visit_Assign(self,node):
            value=node.value
            if isinstance(value,ast.Call) and isinstance(value.func,ast.Name):
                name=value.func.id
                if (len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
                        and ((node.targets[0].id=='actual' and name in ('throughput_active_delta','throughput_native_delta'))
                            or (node.targets[0].id=='current' and name=='throughput_predecessor'
                                and isinstance(value.args[2],ast.Name) and value.args[2].id=='current'))):return None
            return self.generic_visit(node)
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name):
                if node.func.id=='throughput_predecessor':return node.args[2]
                if node.func.id=='throughput_active_delta':return node.args[1]
            return node
    if ast.dump(Strip().visit(ast.parse(updated)))!=ast.dump(tree):
        raise ValueError('every_original_assertion_and_complete_AST_must_be_identical')
    return updated


def literal(raw,name):
    for node in ast.parse(raw).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('original_guard_literal_required:'+name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--runtime',required=True,help='Root-selected full immutable combined runtime SHA')
    parser.add_argument('--out',type=Path,required=True,help='New small staging directory outside checkout')
    parser.add_argument('--template',type=Path,default=TEMPLATE)
    parser.add_argument('--apply',action='store_true',help='Explicit root-owned reviewed generation only')
    args=parser.parse_args();repo=args.repo.resolve();output=args.out.resolve()
    if output==repo or repo in output.parents:raise ValueError('staging_must_be_outside_checkout')
    runtime=git(repo,'rev-parse',args.runtime+'^{commit}').decode().strip()
    if runtime!=args.runtime:raise ValueError('full_exact_runtime_SHA_required')
    if git(repo,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE:raise ValueError('original_44_tree')
    if git(repo,'diff','--name-only',CAPACITY_IMPLEMENTATION,BASE,'--','meme_machine'):
        raise ValueError('44_runtime_must_equal_preserved_managed_cut')
    if git(repo,'diff','--name-only',runtime,'--','meme_machine'):raise ValueError('commit_exact_runtime_before_proof')
    for flags in ((),('--ignored',)):
        extra=git(repo,'ls-files','--others',*flags,'--exclude-standard','--','meme_machine').decode().splitlines()
        if any('__pycache__' not in Path(p).parts and not p.endswith('.pyc') for p in extra):
            raise ValueError('no_unknown_or_ignored_runtime_inputs')
    read=lambda ref,path:git(repo,'show',ref+':'+path)
    protected={}
    for path in PROTECTED:
        body=read(BASE,path)
        if read(runtime,path)!=body or (repo/path).read_bytes()!=body:
            raise ValueError('original_guard_proof_or_managed_pump_changed:'+path)
        protected[path]=dict(bytes=len(body),sha256=checksum(body))
    before_guard=read(BASE,GUARD);after_guard=rewrite_guard(before_guard)
    if (repo/GUARD).read_bytes() not in (before_guard,after_guard):raise ValueError('unknown_managed_guard_bytes')
    files={};test_files={}
    for namespace,target in (('meme_machine',files),('tests',test_files)):
        for line in git(repo,'diff','--name-status',BASE,runtime,'--',namespace).decode().splitlines():
            status,path=line.split('\t')
            if namespace=='tests' and (path in (GUARD,NEW_GUARD,NEW_MANIFEST) or not path.endswith('.py')):continue
            if status not in ('M','A'):raise ValueError('unknown_removal_rename_or_mode_change:'+path)
            if path in PROTECTED:raise ValueError('protected_source_is_not_a_successor_input:'+path)
            before=read(BASE,path) if status=='M' else None;after=read(runtime,path)
            if (repo/path).is_symlink() or (repo/path).read_bytes()!=after:
                raise ValueError('exact_regular_committed_input_required:'+path)
            target[path]=record(before,after,status,path)
    if not files:raise ValueError('nonempty_reviewed_runtime_delta_required')
    legacy_paths=set(literal(before_guard,'MODIFIED'))|set(literal(before_guard,'TEST_CALLERS'))
    legacy={}
    for path in files.keys()|test_files.keys():
        if path in legacy_paths:
            body=read(CAPACITY_BASE,path)
            legacy[path]=dict(reference=CAPACITY_BASE,bytes=len(body),sha256=checksum(body))
    template=args.template.read_bytes();builder=Path(__file__).read_bytes()
    manifest=dict(schema='authenticated-owner-throughput-source-delta-v1',base=BASE,base_tree=BASE_TREE,
        implementation=runtime,implementation_tree=git(repo,'rev-parse',runtime+'^{tree}').decode().strip(),
        capacity_base=CAPACITY_BASE,capacity_implementation=CAPACITY_IMPLEMENTATION,
        files=files,test_files=test_files,legacy_inputs=legacy,protected=protected,
        guard=dict(path=GUARD,**inverse_record(before_guard,after_guard)),
        proof_inputs={NEW_BUILDER:dict(bytes=len(builder),sha256=checksum(builder)),
            NEW_TEMPLATE:dict(bytes=len(template),sha256=checksum(template))})
    raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    source=template.decode()
    values=dict(IMPLEMENTATION=runtime,IMPLEMENTATION_TREE=manifest['implementation_tree'],MANIFEST_SHA256=checksum(raw),
        MODIFIED=repr(tuple(p for p,r in files.items() if r['status']=='M')),
        ADDED=repr(tuple(p for p,r in files.items() if r['status']=='A')),
        TEST_CALLERS=repr(tuple(p for p,r in test_files.items() if r['status']=='M')),
        TEST_ADDED=repr(tuple(p for p,r in test_files.items() if r['status']=='A')),
        LEGACY_PATHS=repr(tuple(sorted(legacy))))
    for name,value in values.items():source=source.replace('@'+name+'@',value)
    if re.search(r'@[A-Z_]+@',source):raise ValueError('unbound_frozen_source_identity')
    ast.parse(source)
    generated={GUARD:after_guard,NEW_GUARD:source.encode(),NEW_MANIFEST:raw,
        NEW_BUILDER:builder,NEW_TEMPLATE:template}
    output.mkdir(parents=True,exist_ok=False)
    for path,body in generated.items():
        destination=output/path;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(body)
    receipt=dict(schema='owner-throughput-proof-generation-v1',runtime=runtime,tree=manifest['implementation_tree'],
        source_proof_only=True,tests_run=False,operational_authority=False,repo_written=args.apply,
        runtime_paths=len(files),test_paths=len(test_files),original_guard_bytes_restored=True,
        staged={p:dict(bytes=len(b),sha256=checksum(b)) for p,b in generated.items()})
    (output/'generation-receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    if args.apply:
        for path,body in generated.items():(repo/path).write_bytes(body)
    print(json.dumps(receipt,sort_keys=True,indent=2))


if __name__=='__main__':main()
