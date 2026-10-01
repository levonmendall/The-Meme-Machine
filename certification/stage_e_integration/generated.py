"""Deterministic byte identity for the one reviewed AST-derived unit helper."""
from types import CodeType
from certification.stage_e_native_v2.contract import canonical, sha256


def code_identity(code):
    def constant(value):
        if isinstance(value, CodeType):
            return fields(value)
        if isinstance(value, bytes):
            return dict(bytes=value.hex())
        if isinstance(value, tuple):
            return dict(tuple=[constant(v) for v in value])
        if value is None or type(value) in (str, int, float, bool):
            return value
        raise ValueError('unsupported_generated_code_constant')

    def fields(value):
        return {name: constant(getattr(value, name)) for name in (
            'co_code', 'co_consts', 'co_names', 'co_varnames', 'co_freevars', 'co_cellvars',
            'co_nlocals', 'co_stacksize', 'co_argcount', 'co_posonlyargcount',
            'co_kwonlyargcount', 'co_flags', 'co_firstlineno', 'co_name', 'co_qualname',
            'co_filename', 'co_linetable', 'co_exceptiontable')}

    return sha256(canonical(fields(code)))
