"""Stage an exact frozen native-audit test-source successor outside the repo.

No default action writes the application checkout.  --apply is a separate,
explicit option for the assigned source owner after runtime freeze/review.
This builder imports no application/test modules and runs no tests/providers.
"""
import argparse
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE='0e9a0ffe1912c28258735909ebce933803585556'
BASE_TREE='8646cdcd1de820e909090f0c1fd899e12dffe9ea'
FILES=('meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/storage.py')
HELPERS=('meme_machine/runtime/native_audit_retention.py',)
GUARDS=('tests/test_ea_performance_source_guard.py',
    'tests/test_operational_candidate_source_guard.py',
    'tests/test_pump_restore_source_guard.py','tests/test_robinhood_usd_valuation.py')
INNER=('tests/fixtures/ea_performance_source_delta.json',
    'tests/fixtures/operational_candidate_source_delta.json',
    'tests/fixtures/pump_restore_reference_source_delta.json')
NEW_GUARD='tests/test_native_audit_source_guard.py'
NEW_MANIFEST='tests/fixtures/native_audit_source_delta.json'
NEW_BUILDER='engineering/diagnostics/build_native_audit_source_proof.py'
NEW_TEMPLATE='engineering/diagnostics/native_audit_source_guard.template.txt'
TEMPLATE=Path(__file__).with_name('native_audit_source_guard.template.txt')
IMPORT='from tests.test_native_audit_source_guard import audit_predecessor, audit_predecessor_runtime_delta\n'


def digest(body):return hashlib.sha256(body).hexdigest()


def git(repo,*args):return subprocess.check_output(['git',*args],cwd=repo)


def hooks(body):
    found=[]
    def walk(node,owner):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            owner=owner+'/'+node.name
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in (
                'audit_predecessor','audit_predecessor_runtime_delta'):
            found.append(dict(caller=owner,call=ast.dump(node)))
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(ast.parse(body),'module')
    return sorted(found,key=lambda row:(row['caller'],row['call']))


def imports(body):
    return sorted(ast.dump(node) for node in ast.walk(ast.parse(body))
        if isinstance(node,(ast.Import,ast.ImportFrom)))


def rally_functions(reference):
    tree=ast.parse(reference)
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef)
        and node.name in ('rally_nodes','rally_delta')]
    if len(selected)!=2:raise ValueError('two_exact_original_rally_functions_required')
    scope={'ast':ast}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<immutable-0e9-rally-functions>','exec'),scope)
    return scope['rally_delta']


def inverse_record(before,after,delta):
    old,new=before.decode().splitlines(keepends=True),after.decode().splitlines(keepends=True)
    changes=[]
    for group in difflib.SequenceMatcher(None,old,new,autojunk=False).get_grouped_opcodes(5):
        first,last=group[0],group[-1]
        prior=''.join(old[first[1]:last[2]])
        successor=''.join(new[first[3]:last[4]])
        if not successor or after.count(successor.encode())!=1:
            raise ValueError('complete_unique_context_hunk_required')
        changes.append(dict(before=prior,after=successor))
    restored=after
    for row in changes:
        if restored.count(row['after'].encode())!=1:raise ValueError('unique_inverse_required')
        restored=restored.replace(row['after'].encode(),row['before'].encode(),1)
    if restored!=before:raise ValueError('complete_whole_byte_inverse_required')
    return dict(before_bytes=len(before),after_bytes=len(after),before_sha256=digest(before),
        after_sha256=digest(after),changes=changes,**delta(before,after))


def offsets(source):
    lines=source.splitlines(keepends=True);starts=[];position=0
    for line in lines:starts.append(position);position+=len(line)
    return lambda n:(starts[n.lineno-1]+n.col_offset,starts[n.end_lineno-1]+n.end_col_offset)


def rewrite_guard(path,raw):
    """Only actual fresh reads and the one explicit current-census boundary."""
    source=raw.decode();tree=ast.parse(source);span=offsets(source);edits=[]
    parents={}
    def walk(node,owner=''):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):owner=node.name
        parents[id(node)]=owner
        for child in ast.iter_child_nodes(node):walk(child,owner)
    walk(tree)
    if path=='tests/test_ea_performance_source_guard.py':
        # All ROOT/path fresh reads in this already-fixed complete guard are
        # explicit source views; raw manifest mutation reads remain untouched.
        for node in ast.walk(tree):
            if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                    and node.func.attr=='read_bytes' and not node.args and not node.keywords
                    and isinstance(node.func.value,ast.BinOp)
                    and isinstance(node.func.value.op,ast.Div)
                    and isinstance(node.func.value.left,ast.Name)
                    and node.func.value.left.id=='ROOT'):
                start,end=span(node);relative=ast.get_source_segment(source,node.func.value.right)
                edits.append((start,end,'audit_predecessor(self,'+relative+','+source[start:end]+')'))
        boundary=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Name) and node.func.id=='git'
            and len(node.args)==5 and not node.keywords
            and ast.dump(node)==ast.dump(ast.parse(
                "git('diff','--name-only',IMPLEMENTATION,'--','meme_machine')",mode='eval').body)
            and parents[id(node)]=='test_complete_three_file_frozen_and_active_runtime_delta']
        if len(boundary)!=1:raise ValueError('one_original_active_runtime_census_required')
        start,end=span(boundary[0])
        edits.append((start,end,'audit_predecessor_runtime_delta(self,'+source[start:end]+')'))
    else:
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Name)
            and node.func.id in ('performance_source','performance_guard_source')]
        for node in calls:
            if len(node.args)!=3 or node.keywords:raise ValueError('original_three_argument_read_hook_required')
            raw_read=node.args[2]
            if (not isinstance(raw_read,ast.Call) or not isinstance(raw_read.func,ast.Attribute)
                    or raw_read.func.attr!='read_bytes' or raw_read.args or raw_read.keywords):
                raise ValueError('only_original_fresh_read_inputs_allowed')
            start,end=span(raw_read)
            owner=ast.get_source_segment(source,node.args[0]);relative=ast.get_source_segment(source,node.args[1])
            edits.append((start,end,'audit_predecessor('+owner+','+relative+','+source[start:end]+')'))
        if path=='tests/test_robinhood_usd_valuation.py':
            # Storage had never belonged to the three-file performance layer.
            # This exact source read must enter its old startup mutation chain
            # only after whole storage authentication/reversal; later mutation
            # and immutable-reference inputs are deliberately not wrapped.
            reads=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
                and isinstance(node.func,ast.Name) and node.func.id=='pump_restore_predecessor'
                and parents[id(node)]=='test_native_startup_failure_delta_preserves_all_prior_authority_and_source_guards'
                and len(node.args)==3 and isinstance(node.args[2],ast.Call)
                and isinstance(node.args[2].func,ast.Attribute) and node.args[2].func.attr=='read_bytes']
            if len(reads)!=1:raise ValueError('one_storage_startup_fresh_read_required')
            node=reads[0];start,end=span(node.args[2])
            edits.append((start,end,'audit_predecessor(self,relative,'+source[start:end]+')'))
    previous_end=-1
    for start,end,_ in sorted(edits):
        if start<previous_end:raise ValueError('nonoverlapping_exact_read_hooks_required')
        previous_end=end
    for start,end,replacement in sorted(edits,reverse=True):source=source[:start]+replacement+source[end:]
    first=ast.parse(source).body[0]
    if not(isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant)
            and isinstance(first.value.value,str)):raise ValueError('original_guard_docstring_required')
    lines=source.splitlines(keepends=True);lines.insert(first.end_lineno,IMPORT);source=''.join(lines)
    # Reversing just the explicit new calls/import must preserve the ENTIRE
    # original guard AST: assertions, hash constants, predecessors, mutations.
    class Strip(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            return None if node.module=='tests.test_native_audit_source_guard' else node
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='audit_predecessor':return node.args[2]
            if isinstance(node.func,ast.Name) and node.func.id=='audit_predecessor_runtime_delta':return node.args[1]
            return node
    if ast.dump(Strip().visit(ast.parse(source)))!=ast.dump(tree):
        raise ValueError('original_complete_guard_AST_must_be_identical')
    return source.encode()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--runtime',required=True,help='Actual immutable root-selected runtime commit; never guessed')
    parser.add_argument('--out',type=Path,required=True,help='Owned small staging directory outside the repo')
    parser.add_argument('--template',type=Path,default=TEMPLATE,
        help='Fixed published template; the preparation owner may supply its outside-repo location')
    parser.add_argument('--apply',action='store_true',help='Explicit source-owner action after freeze/review')
    args=parser.parse_args();repo=args.repo.resolve();output=args.out.resolve()
    if output==repo or repo in output.parents:raise ValueError('default_staging_must_be_outside_checkout')
    runtime=git(repo,'rev-parse',args.runtime+'^{commit}').decode().strip()
    tree=git(repo,'rev-parse',runtime+'^{tree}').decode().strip()
    if git(repo,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE:raise ValueError('immutable_0e9_tree')
    expected={'M\t'+p for p in FILES}|{'A\t'+p for p in HELPERS}
    actual=set(git(repo,'diff','--name-status',BASE,runtime,'--','meme_machine').decode().splitlines())
    if actual!=expected:raise ValueError('exact_three_path_changed_added_runtime_census_required')
    if git(repo,'diff','--name-only',runtime,'--','meme_machine'):
        raise ValueError('working_runtime_not_exact_frozen_candidate')
    for options in ((),('--ignored',)):
        extra=git(repo,'ls-files','--others',*options,'--exclude-standard','--','meme_machine').decode().splitlines()
        if any('__pycache__' not in Path(p).parts and not p.endswith('.pyc') for p in extra):
            raise ValueError('no_unlisted_runtime_source_inputs')
    read=lambda ref,path:git(repo,'show',ref+':'+path)
    baseline={path:read(BASE,path) for path in GUARDS+INNER}
    for path in INNER:
        if (repo/path).read_bytes()!=baseline[path]:raise ValueError('original_0e9_proof_not_intact:'+path)
    delta=rally_functions(baseline['tests/test_robinhood_usd_valuation.py'])
    files={path:inverse_record(read(BASE,path),read(runtime,path),delta) for path in FILES}
    helpers={path:dict(bytes=len(read(runtime,path)),sha256=digest(read(runtime,path)),imports=imports(read(runtime,path))) for path in HELPERS}
    generated={path:rewrite_guard(path,baseline[path]) for path in GUARDS}
    for path,body in generated.items():
        if (repo/path).read_bytes() not in (baseline[path],body):
            raise ValueError('unknown_original_or_generated_guard:'+path)
    guards={path:dict(inverse_record(baseline[path],body,delta),fixed_read_hooks=hooks(body)) for path,body in generated.items()}
    template=args.template.read_bytes()
    builder=Path(__file__).read_bytes()
    proof_inputs={NEW_BUILDER:dict(bytes=len(builder),sha256=digest(builder)),
        NEW_TEMPLATE:dict(bytes=len(template),sha256=digest(template))}
    manifest=dict(schema='authenticated-native-audit-source-delta-v1',base=BASE,base_tree=BASE_TREE,
        implementation=runtime,implementation_tree=tree,files=files,helpers=helpers,guards=guards,
        proof_inputs=proof_inputs,
        inner={path:dict(bytes=len(body),sha256=digest(body)) for path,body in baseline.items() if path in INNER})
    raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();generated[NEW_MANIFEST]=raw
    source=template.decode()
    for key,value in [('IMPLEMENTATION',runtime),('IMPLEMENTATION_TREE',tree),('MANIFEST_SHA256',digest(raw))]:
        source=source.replace('@'+key+'@',value)
    if re.search(r'@[A-Z_]+@',source):raise ValueError('no_unbound_source_identity')
    ast.parse(source);generated[NEW_GUARD]=source.encode()
    generated[NEW_BUILDER]=builder;generated[NEW_TEMPLATE]=template
    declaration="'tests.test_native_audit_source_guard',"
    anchor="'tests.test_ea_performance_source_guard',"
    for path in ('operational/tests.py','.github/workflows/ci.yml'):
        body=read(runtime,path).decode()
        if body.count(anchor)!=1 or declaration in body:raise ValueError('single_existing_guard_registration_required')
        lines=body.splitlines(keepends=True)
        index=next(i for i,line in enumerate(lines) if anchor in line)
        prefix=lines[index][:len(lines[index])-len(lines[index].lstrip())]
        lines.insert(index+1,prefix+declaration+'\n');generated[path]=''.join(lines).encode()
        if path=='.github/workflows/ci.yml':
            native="'tests.test_pons_native_audit_guards',"
            native_anchor="'tests.test_pons_evidence_retention_revision',"
            if body.count(native_anchor)!=1 or native in body:
                raise ValueError('single_existing_native_retention_registration_required')
            index=next(i for i,line in enumerate(lines) if native_anchor in line)
            prefix=lines[index][:len(lines[index])-len(lines[index].lstrip())]
            lines.insert(index+1,prefix+native+'\n');generated[path]=''.join(lines).encode()
        if (repo/path).read_bytes() not in (body.encode(),generated[path]):
            raise ValueError('unknown_original_or_generated_registration:'+path)
    output.mkdir(parents=True,exist_ok=True)
    for path,body in generated.items():
        destination=output/path;destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise ValueError('preserve_existing_staged_artifact:'+str(destination))
        destination.write_bytes(body)
    receipt=dict(schema='native-audit-source-proof-generation-v1',runtime=runtime,tree=tree,
        source_proof_only=True,normal_operation_authority=False,tests_run=False,repo_written=args.apply,
        staged={path:dict(bytes=len(body),sha256=digest(body)) for path,body in generated.items()},
        original_guards_restored_AST=True,original_inner_proofs_unchanged=True)
    (output/'generation-receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    if args.apply:
        for path,body in generated.items():(repo/path).write_bytes(body)
    print(json.dumps(receipt,sort_keys=True,indent=2))


if __name__=='__main__':main()
