"""Native Current decisions and original delayed fills through bounded workers."""
import json
import unittest
from tests import test_pons_current_shared_owners as owners


class CurrentExitSharingTests(unittest.TestCase):
    def run_native(self,n,**kwargs):
        f=owners.CurrentSharedOwnerTests();self.addCleanup(f.doCleanups);return f.run_owners(n,**kwargs)

    def test_two_native_full_and_partial_exits_keep_quantity_basis_and_delayed_fill(self):
        for factor in (.6,2.2):
            old,a,_=self.run_native(2,sharing=False,price_factor=factor)
            new,b,t=self.run_native(2,sharing=True,price_factor=factor)
            for x,y in zip(old,new):
                self.assertEqual(x['final_position'],y['final_position'])
                self.assertEqual(x['reconciliation'],y['reconciliation'])
                self.assertEqual(x['monitor'][0]['action'],y['monitor'][0]['action'])
            self.assertEqual(sum(len(r.transports) for r in b),7)
            self.assertGreater(sum(len(r.transports) for r in a),7)
            for identity in {e['identity'] for e in t['native_events']}:
                row=[e for e in t['native_events'] if e['identity']==identity]
                intent=next(e for e in row if e['action']=='exit_intent')
                fill=next(e for e in row if e['action']=='exit')
                self.assertGreaterEqual(fill['completed_monotonic']-intent['completed_monotonic'],2)

    def test_one_two_four_eight_twelve_twenty_coincident_decisions_and_exits(self):
        for rate in (2,3,4):
            for count in (1,2,4,8,12,20):
                for factor in (.6,2.2):
                    with self.subTest(rps=rate,owners=count,price=factor):
                        results,rpcs,t=self.run_native(count,sharing=True,paced=True,latency=.1,
                            price_factor=factor,rps=rate)
                        self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
                        self.assertEqual(t['protection_turns'],count)
                        self.assertLessEqual(t['peak_physical_workers'],8)
                        marks=[e for e in t['native_events'] if e['action']=='mark']
                        intents=[e for e in t['native_events'] if e['action']=='exit_intent']
                        exits=[e for e in t['native_events'] if e['action']=='exit']
                        self.assertEqual((len(marks),len(intents),len(exits)),(count,count,count))
                        self.assertTrue(all(e['completed_monotonic']-105<5 for e in intents))
                        # The native PAPER fill has its own original two-second
                        # delay. Never mislabel it a late risk observation.
                        self.assertEqual(sum(len(r.transports) for r in rpcs),7)
                        print('NATIVE_CURRENT_EXIT_ENVELOPE',json.dumps(dict(owners=count,rps=rate,
                            action=results[0]['monitor'][0]['action']['action'],
                            risk_decision_seconds=max(e['completed_monotonic'] for e in intents)-105,
                            fill_completed_seconds=max(e['completed_monotonic'] for e in exits)-105,
                            completion_with_local_seconds=t['complete_modeled_with_local_seconds'],
                            original_fill_delay_seconds=2,starts=sorted(s for r in rpcs for s in r.starts),
                            worker=t)),flush=True)

    def test_staggered_native_current_turns_never_rewind_the_admission_clock(self):
        for factor in (1.,.6,2.2):
            for n in (2,8,20):
                results,rpcs,t=self.run_native(n,sharing=True,stagger=True,paced=True,latency=.1,
                    price_factor=factor,rps=4)
                self.assertEqual(t['protection_turns'],n)
                starts=sorted(s for r in rpcs for s in r.starts)
                self.assertTrue(all(b-a>=.25-1e-8 for a,b in zip(starts,starts[1:])))
                self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
                print('NATIVE_CURRENT_STAGGER',json.dumps(dict(owners=n,price_factor=factor,
                    physical_starts=len(starts),worker=t)),flush=True)

    def test_mixed_native_current_and_survivor_owners_share_admission_and_keep_separate_books(self):
        for factor in (1.,.6,2.2):
            with self.subTest(price_factor=factor):
                results,rpcs,t=self.run_native(2,sharing=True,paced=True,latency=.1,
                    price_factor=factor,rps=4,survivor_count=2)
                self.assertTrue(t['mixed_survivor']['native_accounting_verified'])
                self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
                starts=sorted(s for r in rpcs for s in r.starts)
                self.assertTrue(all(b-a>=.25-1e-8 for a,b in zip(starts,starts[1:])))
                print('NATIVE_MIXED_OWNER_ENVELOPE',json.dumps(dict(current_owners=2,survivor_owners=2,
                    price_factor=factor,physical_starts=len(starts),worker=t)),flush=True)

    def test_failed_execution_keeps_original_native_pending_intents_and_recovery(self):
        results,rpcs,t=self.run_native(2,sharing=True,paced=True,latency=.1,price_factor=2.2,rps=4,
            exit_transport_failure=True,allow_capacity_refusal=True)
        for result in results:
            p=result['final_position']
            self.assertEqual(p['status'],'exit_pending')
            self.assertEqual(p['tokens'],p['entry_tokens'])
            self.assertGreater(p['pending_exit_tokens'],0)
            self.assertEqual(p['realized_proceeds'],0)
            self.assertTrue(result['provider_recoveries'])
            self.assertTrue(result['reconciliation']['cash_basis_conservation'])
