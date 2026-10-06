"""Bounded, non-authoritative source selection before canonical work or IPC.

The native parser validates the complete provider JSON into its bounded native
tape. Python only visits transaction identity and static/loaded account keys.
Unrelated instruction, log and balance bodies never become Python objects.
Only retained transactions cross the decoder process boundary. This reduces
local work; the configured provider still transmits the original full frame.
"""
from dataclasses import dataclass
import simdjson
from .solana_evidence_plane import EvidenceUnavailable


@dataclass(frozen=True)
class SelectedFrame:
    message: dict
    source_bytes: int
    source_transactions: int
    retained_transactions: int
    normalized_keys: tuple
    members: dict
    full_body_transactions: int=0
    log_projection_transactions: int=0
    economic_projection_transactions: int=0

    def counters(self):
        return dict(source_bytes=self.source_bytes,
                    inspected_transactions=self.source_transactions,
                    materialized_transactions=self.retained_transactions,
                    discarded_transactions=self.source_transactions-self.retained_transactions,
                    full_body_transactions=self.full_body_transactions,
                    log_projection_transactions=self.log_projection_transactions,
                    economic_projection_transactions=self.economic_projection_transactions)


def _object(value, reason):
    if not isinstance(value, simdjson.Object):
        raise EvidenceUnavailable(reason)
    # Native proxy lookup is first-key-wins, whereas Python dict conversion is
    # last-key-wins. Reject ambiguity in the routing/membership path rather than
    # allowing either interpretation to omit a relevant transaction.
    names=list(value.keys())
    if len(names)!=len(set(names)):
        raise EvidenceUnavailable(reason)
    return value


def _plain(value):
    if isinstance(value, simdjson.Object):return value.as_dict()
    if isinstance(value, simdjson.Array):return value.as_list()
    return value


def _except(value, excluded):
    # Object.items()/values() eagerly recurse in pysimdjson 7.0.2. Iterating
    # names first is essential: do not even access the excluded large subtree.
    return {key:_plain(value[key]) for key in value.keys() if key!=excluded}


def _keys(message, meta):
    keys=message['accountKeys']
    if not isinstance(keys, simdjson.Array):
        raise EvidenceUnavailable('source_transaction_shape')
    normalized=[]
    for key in keys:
        if isinstance(key, simdjson.Object):
            key=_object(key,'source_transaction_shape')['pubkey']
        if not isinstance(key,str):
            raise EvidenceUnavailable('source_transaction_shape')
        normalized.append(key)
    loaded=meta.get('loadedAddresses')
    if loaded is not None:
        loaded=_object(loaded,'source_transaction_shape')
        for side in ('writable','readonly'):
            values=loaded.get(side)
            if values is None:continue
            if not isinstance(values,simdjson.Array):
                raise EvidenceUnavailable('source_transaction_shape')
            for key in values:
                if not isinstance(key,str):
                    raise EvidenceUnavailable('source_transaction_shape')
                normalized.append(key)
    return normalized


def _economic_projection(transaction,message,meta,normalized):
    """Materialize exactly the fields required by canonical DLMM economics.

    Account keys are normalized once, including loaded addresses.  Instructions,
    inner instructions, logs and token balances are the only transaction-body
    fields consumed by the Meteora tape.  Rewards, generic balance arrays, return
    data and unrelated provider metadata never cross the intake boundary.
    """
    instructions=message.get('instructions')
    signatures=transaction.get('signatures')
    if not isinstance(instructions,simdjson.Array) or not isinstance(signatures,simdjson.Array):
        raise EvidenceUnavailable('source_transaction_shape')
    projected_meta={}
    for key in ('err','logMessages','innerInstructions','preTokenBalances','postTokenBalances'):
        value=meta.get(key)
        projected_meta[key]=_plain(value)
    return dict(
        transaction=dict(
            signatures=signatures.as_list(),
            message=dict(accountKeys=list(normalized),instructions=instructions.as_list())),
        meta=projected_meta,
    )


def select_frame(raw, credential, program_addresses, *, max_bytes, full_transaction_addresses=None):
    """Select losslessly; never decode events, hash bodies, write state or use RPC.

    A parser belongs to one call. No native proxies escape, and no global parser
    or shared mutable parser can leak state across concurrent tasks/threads.
    """
    if not isinstance(raw,(str,bytes)) or len(raw)>max_bytes:
        raise EvidenceUnavailable('source_message_size_limit')
    needle=credential.encode() if isinstance(raw,bytes) else credential
    if needle and needle in raw:
        raise ValueError('provider_credential_publication_rejected')
    source_bytes=len(raw.encode()) if isinstance(raw,str) else len(raw)
    if source_bytes>max_bytes:
        raise EvidenceUnavailable('source_message_size_limit')
    parser=simdjson.Parser(max_bytes)
    try:
        root=_object(parser.parse(raw),'source_message_shape')
        if root.get('method')!='blockNotification':
            return SelectedFrame(root.as_dict(),source_bytes,0,0,(),{})
        params=_object(root['params'],'source_block_shape')
        result=_object(params['result'],'source_block_shape')
        value=_object(result['value'],'source_block_shape')
        block=_object(value['block'],'source_block_shape')
        transactions=block['transactions']
        if not isinstance(transactions,simdjson.Array):
            raise EvidenceUnavailable('source_block_shape')
        targets=set(program_addresses)
        full_targets=targets if full_transaction_addresses is None else set(full_transaction_addresses)
        kept=[];normalizations=[];members={}
        full_count=log_count=economic_count=0
        for tx in transactions:
            tx=_object(tx,'source_transaction_shape')
            transaction=_object(tx['transaction'],'source_transaction_shape')
            message=_object(transaction['message'],'source_transaction_shape')
            meta=_object(tx['meta'],'source_transaction_shape')
            normalized=_keys(message,meta)
            matched=targets.intersection(normalized)
            if not matched:continue
            index=len(kept)
            if matched.intersection(full_targets):
                # Meteora requires transaction economics, not the provider's
                # unrelated full body. Retain only its canonical reconstruction
                # vector and the real chain transaction index used for ordering.
                # Later qualification hydrates nothing this vector already has.
                body=_economic_projection(transaction,message,meta,normalized)
                tx_index=tx.get('transactionIndex')
                if tx_index is not None:
                    if type(tx_index) is not int or tx_index<0:
                        raise EvidenceUnavailable('source_transaction_shape')
                    body['transactionIndex']=tx_index
                economic_count+=1
            else:
                # The frozen Pump/PumpSwap census path only consumes signature,
                # account membership, err and logs. Their canonical event body
                # and delivery hash exclude all other transaction fields.
                # Reuse the normalized list instead of duplicating account IPC.
                body=dict(transaction=dict(signatures=_plain(transaction['signatures']),
                    message=dict(accountKeys=normalized)),
                    meta=dict(err=_plain(meta.get('err')),logMessages=_plain(meta.get('logMessages'))))
                log_count+=1
            kept.append(body);normalizations.append(normalized)
            for address in matched:members.setdefault(address,[]).append(index)
        selected_block=_except(block,'transactions');selected_block['transactions']=kept
        selected_value=_except(value,'block');selected_value['block']=selected_block
        selected_result=_except(result,'value');selected_result['value']=selected_value
        selected_params=_except(params,'result');selected_params['result']=selected_result
        selected_root=_except(root,'params');selected_root['params']=selected_params
        return SelectedFrame(selected_root,source_bytes,len(transactions),len(kept),
                             tuple(normalizations),members,full_count,log_count,
                             economic_count)
    except EvidenceUnavailable:raise
    except (KeyError,TypeError,AttributeError):
        raise EvidenceUnavailable('source_transaction_shape') from None
    except (ValueError,RuntimeError,UnicodeError):
        # Native parser errors may include source fragments. Publish only the
        # existing fixed fail-closed reason and retain no raw exception text.
        raise EvidenceUnavailable('source_message_shape') from None
