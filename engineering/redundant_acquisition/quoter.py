"""Inactive exact-code proof of the V4 quoter's immutable manager getter.

Trading controllers do not import this module. It still purchases current code,
gas and the exact simulation; only a compiler-proven getter can be omitted.
Changed/unknown code buys the original getter under the original deadline.
That additional fallback transport needs protective timing proof before use.
"""
from meme_machine.lanes.pons.abi import calldata
from pathlib import Path
from meme_machine.lanes.pons.identity import metadata, compiler_input, verify_compilation
from meme_machine.lanes.pons.pons_natural_paper import V4_QUOTER


def manager_proof():
    from meme_machine.runtime.source_artifacts import REGISTRY
    pin=REGISTRY.get(Path(__file__).with_name('quoter.json'),validate=verify_compilation)
    source=compiler_input(pin)['sources']['src/base/ImmutableState.sol']['content']
    if ('IPoolManager public immutable poolManager;' not in source
            or pin['address'].lower()!=V4_QUOTER.lower()):
        raise ValueError('quoter_immutable_source_identity')
    runtime=pin['runtimeBytecode']
    value=runtime['transformationValues']['immutables']['3490']
    refs=runtime['immutableReferences']['3490']
    if len(refs)!=4 or any(r['length']!=32 for r in refs):
        raise ValueError('quoter_immutable_compiler_reference')
    if value.lower()!='0x'+metadata('uniswap_v4_manager')['address'][2:].lower().zfill(64):
        raise ValueError('quoter_immutable_manager_identity')
    return pin['runtimeBytecode']['onchainBytecode'],value


def candidate_batch(rpc,calls,*,scope):
    """Offline comparison adapter; same current code and publication fence.

No cache, state service, delayed batch formation or extended validity. Missing
source proof keeps the complete original batch. Unknown current code restores
the getter before its caller's ordered canonical fence can publish anything.
"""
    getters=[i for i,(m,p) in enumerate(calls) if m=='eth_call'
        and p[0].get('to','').lower()==V4_QUOTER.lower()
        and p[0].get('data')==calldata('poolManager()')]
    if len(getters)!=1:return rpc.batch(calls,scope=scope)
    index=getters[0];block=calls[index][1][1]
    codes=[i for i,(m,p) in enumerate(calls) if m=='eth_getCode'
        and p[0].lower()==V4_QUOTER.lower() and p[1]==block]
    if len(codes)!=1:return rpc.batch(calls,scope=scope)
    try:expected,manager=manager_proof()
    except (OSError,ValueError,KeyError,TypeError):return rpc.batch(calls,scope=scope)
    reduced=[row for i,row in enumerate(calls) if i!=index]
    values=rpc.batch(reduced,scope=scope)
    if not isinstance(values,list) or len(values)!=len(reduced):
        from meme_machine.lanes.pons import BoundaryError
        raise BoundaryError('pons_immutable_manager_batch_incomplete')
    code=values[codes[0]-(codes[0]>index)]
    if not isinstance(code,str) or code.lower()!=expected.lower():
        manager=rpc.batch([calls[index]],scope=scope)[0]
    values.insert(index,manager)
    return values
