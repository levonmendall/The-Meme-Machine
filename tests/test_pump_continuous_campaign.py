import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from meme_machine import solana_evidence_broker as broker_module
from tests import pump_acceleration_natural_prospective as strategy


class CampaignTests(unittest.TestCase):
    def test_rolling_budget_preserves_the_original_rate(self):
        budget=strategy.RollingAttemptBudget(limit=2)
        self.assertTrue(budget.take(1));self.assertTrue(budget.take(2))
        self.assertFalse(budget.take(3300));self.assertTrue(budget.take(3301))
        self.assertFalse(budget.take(3301.5));self.assertTrue(budget.take(3302))

    def test_retirement_keeps_open_and_pending_state_and_durable_terminal(self):
        history=SimpleNamespace(status=lambda now:dict(complete=True,at=now))
        postgrad={name:dict(graduation_time=100,pool=name+'-pool',history=history)
                  for name in ('expired','open','pending','young')}
        postgrad['young']['graduation_time']=1000
        stream=Mock();report={}
        with tempfile.TemporaryDirectory() as td,patch.object(strategy,'REPORT',Path(td)/'report.json'):
            strategy._retire_postgrad(report,postgrad,{('pending','mode'):{}},{('open','mode'):{}},stream,1100)
            terminal=json.loads((Path(td)/'report.terminal.jsonl').read_text())
        self.assertEqual(set(postgrad),{'open','pending','young'})
        stream.remove_address.assert_called_once_with('expired-pool')
        self.assertEqual(terminal['terminal_reason'],'postgrad_entry_horizon_expired')
        self.assertEqual(terminal['policy_hash'],strategy.FROZEN_POLICY_HASH)
        self.assertEqual(report['retired_postgrad_candidates'],1)

    def test_extended_runtime_is_explicit_and_does_not_mutate_policy(self):
        before=strategy.policy_hash()
        with self.assertRaisesRegex(ValueError,'runtime_bound'):strategy.main(discovery_seconds=14400)
        with patch.object(strategy.ConfirmationBook,'from_files',side_effect=RuntimeError('offline-boundary')):
            with self.assertRaisesRegex(RuntimeError,'offline-boundary'):
                strategy.main(campaign=True,discovery_seconds=14400)
        self.assertEqual(before,strategy.policy_hash())

    def test_stream_retirement_waits_for_ack_and_readd_requires_fresh_begin(self):
        stop=threading.Event();broker=Mock();stream=broker_module.DynamicAddressLogStream('unused',broker,'test',clock=lambda:100)
        stream.add_address('pool');sent=[];queue=[];subscriptions=[0];steps=[0]
        class Socket:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def send(self,raw):
                value=json.loads(raw);sent.append(value)
                if value['method']=='logsSubscribe':
                    subscriptions[0]+=1
                    queue.append(dict(id=value['id'],result=7)) # Provider reuses ID after retirement.
                else:
                    self_outer.assertEqual(broker.stream_stop.call_count,0)
                    queue.append(dict(id=value['id'],result=True))
            def recv(self,**kwargs):
                if queue:return json.dumps(queue.pop(0))
                steps[0]+=1
                if steps[0]==1:stream.remove_address('pool')
                elif steps[0]==2:
                    self_outer.assertEqual(broker.stream_stop.call_count,1)
                    stream.add_address('pool')
                elif steps[0]==3:
                    return json.dumps(dict(method='logsNotification',params=dict(subscription=7,result=dict(
                        context=dict(slot=123),value=dict(signature='new-signature',err=None)))))
                else:stop.set()
                raise TimeoutError()
        self_outer=self
        with patch.object(broker_module,'connect',return_value=Socket()):stream.run(stop)
        self.assertEqual([x['method'] for x in sent],['logsSubscribe','logsUnsubscribe','logsSubscribe'])
        self.assertEqual(broker.stream_begin.call_count,2)
        broker.record_event.assert_called_once()
        self.assertEqual(broker.record_event.call_args.kwargs['signature'],'new-signature')
        self.assertEqual(stream.reconnects,0)
        broker.stream_gap.assert_not_called()
