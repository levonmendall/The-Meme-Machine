import unittest

from meme_machine.dlmm_tape import (
    _materialize_removal_effects,
    transaction_swaps,
)

POOL='FtwzPjTqoFuy8aF8bMBi7QF7UxpdYN5n9YUH6R7DcHjB'
WSOL='So11111111111111111111111111111111111111112'
TOKEN_X='HSUMi4rMgjrx7zRUabw3ogGu1pa5hmF2eVcXj9Apump'

TX={
    'slot':449907325,'blockTime':1790220695,'transactionIndex':48,
    'transaction':{
        'signatures':['5PeXkA5PLLR39ZecnB2khGcLiqPjUoDnK2kERgcZLSY8qpWFJEwdUnK5sJuULFPqBeJ2VzKFxFsQtnKZyb6jwM3J'],
        'message':{
            'accountKeys':[
                '5TUvWjeid81ivRQTWSQ6ibfst4x6XGinMWW3J4EkGoug',
                '8c1cuLKg2UscdNysRJGnHJYMoTkZM4RpdFoypdm9Eg1X',
                '9wwcfFFgpxz88o7Q28mc3qVoFn1nzafbkGbtrbFTC483',
                'BpFuDm9jPdaEmo28bgBaWLsGjivgfzzp46UvWo4YULoN',
                'BTYRkD6nZqpsE4ZxX6adpxjstKs81azc9epp2tfMKtcU',
                POOL,'JDRas7Us3QTEorcksLEdXtKHV8pvaXdSztyqybRegFJK',
                'ComputeBudget111111111111111111111111111111',
                'D1ZN9Wj1fRSUQfCjhvnu1hqDMT7hzjzBBpi12nVniYD6',
                'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo',
                WSOL,'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'],
            'instructions':[
                {'accounts':[],'data':'K1FDJ7','programIdIndex':7,'stackHeight':1},
                {'accounts':[2,5,9,1,6,10,4,3,0,11,8,9],
                 'data':'2zPT21iXp216wKwavTu8rK2psbT6LG84VVZwLRjgixomihXExaixqMT1kQXDcei78BghzcokuWu7QkyBiLgejgs6Fmg41apGS6bmE1DTRhYJDNDVWej8yasbzYsWXaJmoyTdicitxWB8Y3rjYd4FmxQTh1MU5bMbwP3fywpnNhFD3vz6pRS1LmtmTqwfEvBm4TW7Buipyb7dw4HGY8Sz9zM24R8MMn33uSex6tXgjfeRfq3nCVVAQfkW2mv3odQeBcqnvsps5g6b2DjZ4bwDb3doCEtvurYkbyibefhseWMS12eyo7Psuy1YRKcfy3HthnNmC7gpofpE3o3T2m4Ae8',
                 'programIdIndex':9,'stackHeight':1},
            ],
        },
    },
    'meta':{
        'err':None,'loadedAddresses':{'readonly':[],'writable':[]},
        'innerInstructions':[{'index':1,'instructions':[
            {'accounts':[1,10,6,0],'data':'ityGa1qVDe8Xz','programIdIndex':11,'stackHeight':2},
            {'accounts':[8],
             'data':'3drYVtAcBYiKzmNPkzG2oeiJZJhQJJf8AunFBojyjbE46jP6BKJiFJsgoxUjXk4EbQQz8ChhRacP3dNBnvHfNV1RWuKDaZjVK74jusuMdASucpL6vKTthecu4d6uSf2u2H9Xdaf7UzwGvHoX1PN8q9mQ22aX6yF7dJtiMXQLdJcHxUc9ZiRJW',
             'programIdIndex':9,'stackHeight':2},
        ]}],
        'preTokenBalances':[
            {'accountIndex':1,'mint':WSOL,'owner':'5TUvWjeid81ivRQTWSQ6ibfst4x6XGinMWW3J4EkGoug',
             'programId':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
             'uiTokenAmount':{'amount':'786069230','decimals':9,'uiAmount':0.78606923,'uiAmountString':'0.78606923'}},
            {'accountIndex':6,'mint':WSOL,'owner':POOL,
             'programId':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
             'uiTokenAmount':{'amount':'600217509224','decimals':9,'uiAmount':600.217509224,'uiAmountString':'600.217509224'}},
        ],
        'postTokenBalances':[
            {'accountIndex':1,'mint':WSOL,'owner':'5TUvWjeid81ivRQTWSQ6ibfst4x6XGinMWW3J4EkGoug',
             'programId':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
             'uiTokenAmount':{'amount':'19','decimals':9,'uiAmount':1.9e-08,'uiAmountString':'0.000000019'}},
            {'accountIndex':6,'mint':WSOL,'owner':POOL,
             'programId':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
             'uiTokenAmount':{'amount':'601003578435','decimals':9,'uiAmount':601.003578435,'uiAmountString':'601.003578435'}},
        ],
    },
}


class LegacyOneSideReplayTest(unittest.TestCase):
    def test_captured_mainnet_instruction_event_transfer_and_rounding(self):
        adjustments=[]
        self.assertEqual(transaction_swaps(TX,POOL,adjustments),[])
        self.assertEqual(len(adjustments),1)
        item=adjustments[0]
        self.assertEqual(item['kind'],'add_liquidity_one_side')
        self.assertEqual(item['max_amount'],786069230)
        self.assertEqual(item['amount_x'],0)
        self.assertEqual(item['amount_y'],786069211)
        self.assertEqual(item['active'],-489)
        self.assertEqual(item['deposit_side'],'y')
        self.assertEqual(item['token_mint'],WSOL)
        self.assertEqual(item['recipient_auth'],'ordered_spl_transfer')
        self.assertEqual(len(item['weights']),37)

        start={
            'step':25,'active':-489,'x':TOKEN_X,'y':WSOL,
            'bins':{str(bid):{} for bid in range(-595,-558)},
        }
        _materialize_removal_effects(start,start,adjustments)
        deposits=item['bin_deposits']
        self.assertEqual(len(deposits),37)
        self.assertEqual(sum(row['y'] for row in deposits),786069211)
        self.assertEqual(item['rounding_dust'],19)
        self.assertEqual(deposits[0],{'bin_id':-595,'x':0,'y':25543620})
        self.assertEqual(deposits[-1],{'bin_id':-559,'x':0,'y':16977089})

    def test_unproven_ask_side_remains_fail_closed(self):
        item={
            'kind':'add_liquidity_one_side','deposit_side':'x',
            'token_mint':TOKEN_X,'active':0,'max_amount':100,
            'amount_x':100,'amount_y':0,'weights':[{'bin_id':1,'weight':1}],
        }
        start={'step':25,'active':0,'x':TOKEN_X,'y':WSOL,'bins':{'1':{}}}
        with self.assertRaisesRegex(Exception,'ask_side_unproven'):
            _materialize_removal_effects(start,start,[item])


if __name__=='__main__':
    unittest.main()
