"""Independent JSON oracle for the repaired economic source contract.

The full preserved transaction remains the reference for every required field.
This helper does not call the native intake or any production projection code.
It is used to compare both prepared and serial ingestion to the same contract,
while retaining the original provider delivery size in their accounting.
"""
import copy


def economic_source_reference(message,subscriptions):
    result=copy.deepcopy(message)
    originals=message['params']['result']['value']['block']['transactions']
    targets={s.address for s in subscriptions}
    economic_targets={s.address for s in subscriptions if s.evidence_class=='transactions'}
    expected=[]
    for original in originals:
        transaction=original['transaction'];meta=original['meta']
        source=transaction['message']
        keys=[key['pubkey'] if isinstance(key,dict) else key for key in source['accountKeys']]
        loaded=meta.get('loadedAddresses') or {}
        keys.extend(loaded.get('writable',[]));keys.extend(loaded.get('readonly',[]))
        if not targets.intersection(keys):continue
        body={'transaction':{'signatures':copy.deepcopy(transaction['signatures']),
                             'message':{'accountKeys':keys}},
              'meta':{key:copy.deepcopy(meta.get(key)) for key in ('err','logMessages')}}
        if economic_targets.intersection(keys):
            body['transaction']['message']['instructions']=copy.deepcopy(source['instructions'])
            for key in ('innerInstructions','preTokenBalances','postTokenBalances'):
                body['meta'][key]=copy.deepcopy(meta.get(key))
        if original.get('transactionIndex') is not None:
            body['transactionIndex']=original['transactionIndex']
        expected.append(body)
    result['params']['result']['value']['block']['transactions']=expected
    return result
