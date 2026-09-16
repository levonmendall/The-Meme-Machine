"""Read-only classification of naturally nominated Pump.fun bonding curves.

This is diagnostic evidence only. It does not nominate, qualify, size, reserve,
or create any paper position. It reports only public account mode fields needed
to decide whether the current adapter is rejecting a faithfully modelable Pump
surface.
"""
import json
import os
import struct

from meme_machine import pump
from meme_machine.provider import RPC

# Naturally nominated mints observed by bounded prospective runs on 2026-09-16.
MINTS = [
    '48JUTuZdUntVrucTCm8zeh6udgPMx11HTnWHkvNspump',
    'FoF6inf4CfwfQyYsW5HSRwQhqG4ATJdFj9bVMzTXpump',
    'Dav2P5wxjJSVFMHeC6xikQdfF34MUSKBcQtYmpZGpump',
    '54YZDUcsH9gTPqfiHKVvdANNVn5kwAXQYBLaDBJUpump',
    '5Re47wrh5ww6RUfLndqpRr24VA3XGzCVLzkQ93GCpump',
    '3NPxFq3VBo3br7uN2HLEiMK1sc71vMtxDUcmoXwQpump',
    'DpWgCP4NP9cxx1DZqqUUwH2iG8A4zJ7K22um8vA7pump',
    'EuwsV7g3tZAgP4Ba3vY6H8FQE8EU6mm9v3sz8p8ypump',
    '9JvoPJuSzGTMUrLwHZNBooDG51wDR2W3HrLc4kFMpump',
    '76jrkpve6zE1fMwYbTs7gk6E43Sx82Qe89kMBq4epump',
]


def classify_curve(account):
    raw = pump.raw_account(account, pump.PROGRAM, 'BondingCurve')
    if len(raw) < 49:
        raise ValueError('unsupported short curve')
    quote_raw = raw[83:115] if len(raw) >= 115 else b'\0' * 32
    quote_mint = None if not any(quote_raw) else pump.b58(quote_raw)
    return {
        'curve_data_len': len(raw),
        'curve_token_total_supply': struct.unpack_from('<Q', raw, 40)[0],
        'is_mayhem_mode': bool(raw[81]) if len(raw) > 81 else False,
        'is_cashback_coin': bool(raw[82]) if len(raw) > 82 else False,
        'quote_mint': quote_mint,
        'creator_fee_bps': struct.unpack_from('<Q', raw, 115)[0] if len(raw) >= 123 else 0,
        'can_edit_creator_fee': bool(raw[123]) if len(raw) > 123 else False,
        'is_holder_reward': bool(raw[124]) if len(raw) > 124 else False,
    }


def main():
    rpc = RPC(os.environ.get('MM_SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com'), limit=40)
    if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
        raise RuntimeError('unsupported_network')
    pools = [pump.pda([b'bonding-curve', pump.un58(mint)]) for mint in MINTS]
    addresses = [x for pair in zip(pools, MINTS) for x in pair]
    result = rpc.call('getMultipleAccounts', [addresses, {'encoding':'base64','commitment':'finalized'}], priority=True)
    accounts = result['value']
    rows = []
    for i, (mint, pool) in enumerate(zip(MINTS, pools)):
        curve_account, mint_account = accounts[2*i], accounts[2*i+1]
        row = {'mint': mint, 'pool': pool}
        try:
            row.update(classify_curve(curve_account))
            mint_supply, decimals = pump.mint_info(mint_account)
            row.update(mint_supply=mint_supply, mint_decimals=decimals,
                       supply_delta=mint_supply-row['curve_token_total_supply'])
        except Exception as exc:
            row['classification_error'] = type(exc).__name__ + ':' + str(exc)
        rows.append(row)
    print(json.dumps({
        'kind': 'read_only_curve_mode_inspection',
        'network': 'solana-mainnet',
        'protocol': 'pump.fun',
        'requests': rpc.calls,
        'failures': rpc.failures,
        'failure_kinds': rpc.failure_kinds,
        'rows': rows,
        'paper_trades': 0,
        'order_authority': False,
        'provider_spend_usd': 0,
        'infrastructure_spend_usd': 0,
    }, sort_keys=True))


if __name__ == '__main__':
    main()
