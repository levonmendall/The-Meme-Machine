import unittest
from unittest.mock import patch
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses import ramses_universe as universe
from meme_machine.lanes.ramses import ramses_capture as capture
from meme_machine.lanes.ramses.abi import calldata


class Session:
    def __init__(self,*args,limit=200,**kwargs):self.used=0;self.limit=limit
    def call(self,method,params,scope):self.used+=1;return '0x1237'
    def batch(self,calls,scope):
        self.used+=len(calls)
        assert self.used<=self.limit
        words=lambda values:'0x'+''.join(f'{v:064x}' for v in values)
        out=[]
        for method,params in calls:
            data=params[0]['data'];selector=data[:10]
            if selector==calldata('getActiveId()')[:10]:values=[1<<23]
            elif selector==calldata('getReserves()')[:10]:values=[1000,2000]
            elif selector==calldata('getProtocolFees()')[:10]:values=[0,0]
            elif selector==calldata('getStaticFeeParameters()')[:10]:values=[0]*7
            elif selector==calldata('getVariableFeeParameters()')[:10]:values=[0]*4
            elif selector==calldata('getBin(uint24)',0)[:10]:values=[10,20]
            elif selector==calldata('totalSupply(uint256)',0)[:10]:values=[5000]
            else:values=[0]
            out.append(words(values))
        return out


class StateBudgetTests(unittest.TestCase):
    def hydrate(self,rpc,count):
        for n in range(count):
            auth,state=universe._prestate(rpc,'factory',f'pool-{n}',100,bin_radius=100,
                                         authenticated_pool={'bin_step':1})
            self.assertEqual(len(state['bins']),201)
            self.assertTrue(all(row=={'reserves':[10,20],'supply':5000} for row in state['bins'].values()))

    def test_old_shared_budget_fails_before_four_required_prestates_complete(self):
        with patch.object(capture,'configured_dlmm_rpc',side_effect=Session):
            rpc=capture.BoundedMultiRpc('https://robinhood-mainnet.g.alchemy.com/v2/offline',max_sessions=7,batch_size=8,batch_pause=0)
            with self.assertRaisesRegex(BoundaryError,'program_budget_exhausted'):self.hydrate(rpc,4)

    def test_exact_maximum_frozen_workload_fits_without_narrowing_or_changing_rate(self):
        frontier={'number':'0x64','hash':'0x'+'ab'*32}
        with patch.object(capture,'configured_dlmm_rpc',side_effect=Session),patch.object(capture.time,'sleep'):
            rpc=universe._state_reader('https://robinhood-mainnet.g.alchemy.com/v2/offline',8,frontier)
            self.hydrate(rpc,8)
            self.assertEqual(sum(s.used for s in rpc.sessions),3265)
            self.assertEqual(rpc.max_sessions,17)
            self.assertEqual(rpc.batch_size,8);self.assertEqual(rpc.batch_pause,.8)
            self.assertEqual(rpc.rate_retries,2);self.assertEqual(rpc.rate_cooldown,8)
            self.assertEqual(rpc.scan_budget['metadata_program_logical_limit'],1400)
            self.assertTrue(all(s.evidence_pins=={'0x64':frontier['hash']} for s in rpc.sessions))
        for count in (0,9,True):
            with self.assertRaisesRegex(BoundaryError,'candidate_bound'):universe._state_reader('https://robinhood-mainnet.g.alchemy.com/v2/offline',count,frontier)


if __name__=='__main__':unittest.main()
