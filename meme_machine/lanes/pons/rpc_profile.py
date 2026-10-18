"""Original optional Pons optimization parsers, independent of transport URLs.

These are request-shaping hints. Chain/deployment/canonical evidence, observed
resource envelopes and independent callMany parity remain native prerequisites.
"""
from . import CHAIN_ID


def apply_rpc_row(rpc,row,domain,maximum):
    try:
        methods=row['methods']
        rpc.hash_state_supported={m for m in ('eth_call','eth_getCode')
            if methods.get('eip1898_'+m,{}).get('supported') is True}
        limits=methods.get('native_quote_batch',{}).get('observed_limits',{})
        integers=('max_response_bytes','max_logical_elements','max_throughput_cu')
        latency=limits.get('max_latency_seconds')
        if (row.get('chain_id')==CHAIN_ID and row.get('provider_domain')==domain
                and row.get('provider_fingerprint')==rpc.provider_fingerprint
                and {'eth_call','eth_getCode'}<=rpc.hash_state_supported
                and methods.get('native_quote_batch',{}).get('supported') is True
                and limits.get('validated') is True
                and all(type(limits.get(k)) is int and limits[k]>0 for k in integers)
                and limits['max_response_bytes']<=maximum
                and limits['max_logical_elements']<=50
                and type(latency) in (int,float) and 0<=latency<=1):
            rpc.shared_quote_resources={k:limits[k] for k in (*integers,'max_latency_seconds')}
            rpc.shared_quote_resources.update(validated=True,provider_fingerprint=rpc.provider_fingerprint)
    except (ValueError,KeyError,TypeError,AttributeError):pass


def apply_context_row(context,row,domain):
    try:context.block_receipts_supported=row['methods']['eth_getBlockReceipts']['supported'] is True
    except (ValueError,KeyError,TypeError,AttributeError):pass
    try:
        resources=row['methods']['eth_getBlockReceipts']['observed_limits']
        if row.get('chain_id')==CHAIN_ID and row.get('provider_domain')==domain:
            context.block_receipts_resources=resources
    except (ValueError,KeyError,TypeError,AttributeError):pass
    try:context.view_batch_state['supported']=row['methods']['eth_callMany']['supported'] is True
    except (ValueError,KeyError,TypeError,AttributeError):pass
