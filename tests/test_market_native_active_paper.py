import unittest

from tests.market_native_active_paper import (
    _first_filled_order,
    _has_reserved_order,
    _order_summary,
    _target_terminal,
)


class ActivePaperProofBoundary(unittest.TestCase):
    def test_first_filled_order_is_deterministic(self):
        state={'orders':{
            'later':dict(status='settled',fill={'time':12},created=12,mint='b'),
            'reserved':dict(status='reserved',created=9,mint='c'),
            'first':dict(status='settled',fill={'time':11},created=11,mint='a'),
        }}
        oid,order=_first_filled_order(state)
        self.assertEqual(oid,'first')
        self.assertEqual(order['mint'],'a')
        self.assertTrue(_has_reserved_order(state))

    def test_terminal_requires_recorded_exit_and_closed_position(self):
        state={'orders':{'x':dict(status='settled',mint='m',fill={'time':1})},
               'positions':{'m':dict()}}
        self.assertFalse(_target_terminal(state,'x'))
        state['orders']['x']['exit']={'reason':'risk','realized':-1}
        self.assertFalse(_target_terminal(state,'x'))
        state['positions'].clear()
        self.assertTrue(_target_terminal(state,'x'))

    def test_summary_preserves_market_native_and_real_snapshot_provenance(self):
        order=dict(
            status='settled',mint='m',created=10,due=12,
            nomination=dict(id='n',discovery_source='market_native',market_time=9),
            evidence=dict(snapshot=dict(kind='real',slot=7),concentration_bps=1234),
            fill=dict(slot=8,market_time=12,available_time=12,time=13,tokens=5,cost=4,fee=1,gas=1),
            exit=dict(reason='take_profit',proceeds=6,fee=1,gas=1,realized=1,time=20,
                      snapshot=dict(protocol='pump.fun')),
        )
        row=_order_summary('n',order)
        self.assertEqual(row['nomination_source'],'market_native')
        self.assertEqual(row['qualification_snapshot_kind'],'real')
        self.assertEqual(row['exit']['reason'],'take_profit')
        self.assertEqual(row['exit']['surface'],'pump.fun')


if __name__=='__main__':
    unittest.main()
