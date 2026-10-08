"""Offline import inventory used before operational branch cleanup."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def modules():
    result={}
    for surface in ('meme_machine','dashboard','tests','operational'):
        for path in (ROOT/surface).rglob('*.py'):
            if '__pycache__' in path.parts:continue
            parts=list(path.relative_to(ROOT).with_suffix('').parts)
            if parts[-1]=='__init__':parts.pop()
            result['.'.join(parts)]=path
    return result

def closure(roots,mapping):
    pending=list(roots);seen=set();external=set()
    while pending:
        name=pending.pop()
        if name in seen:continue
        if name.startswith('certification'):raise AssertionError('historical runtime import: '+name)
        if name not in mapping:
            external.add(name.split('.')[0]);continue
        seen.add(name);path=mapping[name]
        package=name if path.name=='__init__.py' else name.rpartition('.')[0]
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):pending.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):
                base=package.split('.')[:len(package.split('.'))-node.level+1] if node.level else []
                if node.module:base.extend(node.module.split('.'))
                imported='.'.join(base)
                pending.append(imported)
                pending.extend(imported+'.'+a.name for a in node.names if imported+'.'+a.name in mapping)
            elif isinstance(node,ast.Constant) and isinstance(node.value,str):
                # Native adapters and test patch targets also name modules as strings.
                value=node.value
                if value.startswith(('meme_machine.','tests.','dashboard.')):
                    pieces=value.split('.')
                    while pieces and '.'.join(pieces) not in mapping:pieces.pop()
                    if pieces:pending.append('.'.join(pieces))
        prefix=name.split('.')
        for i in range(1,len(prefix)):
            parent='.'.join(prefix[:i])
            if parent in mapping:pending.append(parent)
    return sorted(str(mapping[n].relative_to(ROOT)) for n in seen),sorted(external)

def inventory():
    from operational.tests import OPERATIONAL
    mapping=modules()
    contract=json.loads((ROOT/'operational/runtime-resource-contract.json').read_text())
    missing=set(contract['required_runtime_modules'])-set(mapping)
    assert not missing, 'required runtime modules missing: '+','.join(sorted(missing))
    # Preserve the ordinary committed lane source, including frozen helpers.
    runtime_roots=[n for n in mapping if n.startswith(('meme_machine.lanes.','meme_machine.runtime.','meme_machine.operational.'))]
    runtime_roots+=contract['required_runtime_modules']
    runtime,imports=closure(runtime_roots,mapping)
    tests,_=closure(OPERATIONAL+['operational.tests'],mapping)
    contract=json.loads((ROOT/'operational/runtime-resource-contract.json').read_text())
    # Fixed consumer-reviewed contract: deleting a resource cannot delete its
    # obligation by making rglob() stop seeing it.
    resources=contract['required_packaged_resources']
    assert all((ROOT/p).is_file() for p in resources), 'required non-Python resource missing'
    return dict(result='PASS',runtime_import_files=runtime,test_import_files=tests,
                runtime_resource_files=sorted(resources),
                runtime_external_import_roots=imports,certification_imports=[],
                dynamic_resource_contract=contract,
                note='Static module closure plus explicit dynamic entrypoints/resource contract. Consumer tests exercise role resources; optional/generated resources have no packaged-state obligation.')

if __name__=='__main__':print(json.dumps(inventory(),indent=2))
