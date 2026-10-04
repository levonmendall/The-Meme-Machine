"""Pinned Ramses source attribution; read-only engineering comparison."""
import ast,hashlib

class Plumbing(ast.NodeTransformer):
    """Remove only enumerated operational adapters for economic AST comparison."""
    def visit_Constant(self,node):
        if isinstance(node.value,str):
            for old,new in ENV.items():node.value=node.value.replace(old,new)
            node.value=node.value.replace('certification.','meme_machine.runtime.')
        return node
    def visit_ImportFrom(self,node):
        if node.module=='meme_machine.runtime.storage' or node.module=='meme_machine.runtime.native_boundary':return None
        if node.module:node.module=node.module.replace('certification.','meme_machine.runtime.')
        return node
    def visit_FunctionDef(self,node):
        if node.name=='_stop_sleep':return None
        return self.generic_visit(node)
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):return None
        call=node.value
        if isinstance(call,ast.Call):
            if isinstance(call.func,ast.Name) and call.func.id=='audit_ring':return None
            if isinstance(call.func,ast.Attribute) and call.func.attr=='execute' and call.args and isinstance(call.args[0],ast.Constant):
                sql=call.args[0].value
                if isinstance(sql,str) and any(sql.startswith('DELETE FROM '+table+' ') for table in ('evidence','gas_quotes')):return None
        return self.generic_visit(node)
    def visit_Assign(self,node):
        if any(isinstance(t,ast.Attribute) and t.attr=='portfolio' for t in node.targets):return None
        return self.generic_visit(node)
    def visit_If(self,node):
        text=ast.unparse(node.test)
        if text in ("getattr(self, 'portfolio', None)","self.records >= 8192"):return None
        return self.generic_visit(node)
    def visit_Call(self,node):
        if isinstance(node.func,ast.Name) and node.func.id=='_stop_sleep':node.func=ast.Attribute(value=ast.Name(id='time',ctx=ast.Load()),attr='sleep',ctx=ast.Load())
        node.keywords=[k for k in node.keywords if k.arg!='retention']
        return self.generic_visit(node)

ENV={'MM_CERTIFICATION_RUN_ID':'MM_PAPER_EPOCH','MM_CERTIFICATION_LANE':'MM_RUNTIME_LANE',
     'MM_CERTIFICATION_RPC_CACHE_DB':'MM_RPC_CACHE_DB','MM_CERTIFICATION_RPC_CAPABILITIES':'MM_RPC_CAPABILITIES',
     'MM_CERTIFICATION_PROVIDER_DB':'MM_PROVIDER_DB'}

class Namespace(ast.NodeTransformer):
    def __init__(self,path):
        mod=path.removesuffix('.py').replace('/','.')
        self.package=mod.removesuffix('.__init__') if mod.endswith('.__init__') else mod.rpartition('.')[0]
    def name(self,name):return name.replace('meme_machine.lanes.ramses','robinhood_research')
    def visit_Import(self,node):
        for alias in node.names:alias.name=self.name(alias.name)
        return node
    def visit_ImportFrom(self,node):
        name=node.module or ''
        if node.level:
            parts=self.package.split('.')
            name='.'.join(parts[:len(parts)-node.level+1]+([name] if name else []))
        node.module=self.name(name);node.level=0
        return node
    def visit_Constant(self,node):
        if isinstance(node.value,str):node.value=self.name(node.value)
        return node

def economic_ast(source,path):
    return ast.dump(Plumbing().visit(Namespace(path).visit(ast.parse(source))),include_attributes=False)

def economic_sha256(source,path):
    return hashlib.sha256(economic_ast(source,path).encode()).hexdigest()

