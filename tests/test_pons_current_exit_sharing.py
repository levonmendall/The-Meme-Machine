"""Native Current decisions and original delayed fills through bounded workers."""
import json
import unittest
from unittest.mock import patch
from meme_machine.lanes.pons import BoundaryError
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

    def test_single_exit_retains_native_identity_reuse_without_extra_provider_elements(self):
        for factor in (.6,2.2):
            old,a,_=self.run_native(1,sharing=True,price_factor=factor,exit_sharing=False)
            new,b,_=self.run_native(1,sharing=True,price_factor=factor)
            self.assertEqual(old[0]['final_position'],new[0]['final_position'])
            self.assertEqual(old[0]['reconciliation'],new[0]['reconciliation'])
            self.assertEqual(sum(len(r.transports) for r in a),sum(len(r.transports) for r in b))
            self.assertEqual([dict(r.methods) for r in a],[dict(r.methods) for r in b])

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
            # Clock monotonicity is independent of the configured rate. The
            # 286626b6 OPERATIONAL run demonstrated that twenty staggered exits
            # can exhaust native execution admission at four RPS. Use the
            # existing tested fixture profiles, retaining all successful fill,
            # quantity, accounting and original timing assertions. These
            # guarded offline profiles never change production's two RPS.
            for n,rate in ((2,4),(8,8),(20,12)):
                with self.subTest(owners=n,rps=rate,price_factor=factor):
                    results,rpcs,t=self.run_native(n,sharing=True,stagger=True,paced=True,latency=.1,
                        price_factor=factor,rps=rate)
                    self.assertEqual(t['protection_turns'],n)
                    starts=sorted(s for r in rpcs for s in r.starts)
                    self.assertTrue(all(b-a>=1/rate-1e-8 for a,b in zip(starts,starts[1:])))
                    self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
                    marks=[e for e in t['native_events'] if e['action']=='mark']
                    self.assertEqual(len(marks),n)
                    for event in marks:
                        sequence=int(event['identity'].rsplit(':',1)[1])
                        self.assertLessEqual(event['completed_monotonic'],105+sequence*.1+5)
                    if factor!=1:
                        exits=[e for e in t['native_events'] if e['action']=='exit']
                        self.assertEqual(len(exits),n)
                        for event in exits:
                            intent=next(e for e in t['native_events'] if e['identity']==event['identity']
                                and e['action']=='exit_intent')
                            # Native PAPER stores integer observation time and
                            # due=that time+two. Completion after the SQLite
                            # commit is a different clock; preserve the actual
                            # original due and post-delay quote requirements.
                            self.assertEqual(intent['native_due'],intent['native_at']+2)
                            self.assertGreaterEqual(event['native_at'],intent['native_due'])
                            self.assertGreaterEqual(event['quote_observed_at'],intent['native_due'])
                    print('NATIVE_CURRENT_STAGGER',json.dumps(dict(owners=n,rps=rate,price_factor=factor,
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

    def test_execution_admission_deadline_preserves_original_due_quantity_and_money(self):
        purchase=owners.ActiveRPC.purchase;refusals=[]
        def expired_admission(rpc,*args,**kwargs):
            if rpc.clock>=107:
                refusals.append(rpc.clock)
                raise BoundaryError('provider_shared_admission_deadline')
            return purchase(rpc,*args,**kwargs)
        with patch.object(owners.ActiveRPC,'purchase',expired_admission):
            results,rpcs,t=self.run_native(2,sharing=True,paced=True,latency=.1,price_factor=2.2,
                rps=4,allow_capacity_refusal=True)
        self.assertTrue(refusals)
        self.assertFalse(any(e['action']=='exit' for e in t['native_events']))
        for result in results:
            p=result['final_position']
            intent=next(e for e in t['native_events'] if e['identity']==p['id'] and e['action']=='exit_intent')
            self.assertEqual(p['status'],'exit_pending')
            self.assertEqual(p['tokens'],p['entry_tokens'])
            self.assertEqual(p['pending_exit_tokens'],p['entry_tokens']//4)
            self.assertEqual(p['due'],intent['native_at']+2)
            self.assertEqual(p['realized_proceeds'],0)
            self.assertTrue(result['provider_recoveries'])
            self.assertTrue(result['reconciliation']['cash_basis_conservation'])

    def test_real_clock_mixed_native_queue_and_execution_keep_original_accounting(self):
        for current,survivors,rate in ((2,2,4),(10,10,8)):
            results,rpcs,t=self.run_native(current,sharing=True,paced=True,latency=.1,price_factor=2.2,
                rps=rate,survivor_count=survivors,real_time=True,allow_capacity_refusal=True)
            self.assertTrue(t['mixed_survivor']['native_accounting_verified'])
            self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
            print('REAL_CLOCK_MIXED_PARTIAL',json.dumps(dict(current=current,survivors=survivors,rps=rate,
                physical_starts=sum(len(r.starts) for r in rpcs),starts=sorted(s for r in rpcs for s in r.starts),
                responses=sorted(s for r in rpcs for s in r.responses),queue_wait_seconds=sum(sum(r.waits) for r in rpcs),
                worker=t)),flush=True)
