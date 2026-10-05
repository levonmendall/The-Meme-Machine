"""Current-state chain authentication uses the original candidate admission budget."""
import collections,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
from meme_machine.lanes.pons.provider_admission import Admission,priority,position_work

MODULE='meme_machine.lanes.pons.pons_selective_acquisition'

class RPC:
    canonical_authority=True
    chain_verified=True
    provider_fingerprint="offline_fixture"
    def __init__(self,verify=None,used=0):
        self.used=used;self.per_scope=190;self.counts=collections.Counter()
        self.verify=verify;self.auth_calls=0
    def verify_chain(self):
        self.auth_calls+=1
        if self.verify:self.verify(self)
    def telemetry(self):return {'used':self.used,'auth_calls':self.auth_calls}

class AuthenticationDeadlineTests(unittest.TestCase):
    def test_first_session_has_original_deadline_and_foreground_priority_before_auth(self):
        observed=[]
        rpc=RPC(lambda current:observed.append((current.evidence_deadline,priority('connectivity'))))
        ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.deadline=104.25
        with patch(MODULE+'.configured_rpc',return_value=rpc) as factory:
            self.assertIs(ctx.acquire(16,'pons_natural'),rpc)
        self.assertEqual(observed,[(104.25,10)])
        factory.assert_called_once_with(ctx.endpoint,limit=200,per_scope=190,retries=0)
        self.assertEqual(priority('connectivity'),50)

    def test_shared_wait_expires_at_original_deadline_without_transport(self):
        now=[100.0]
        def sleep(seconds):now[0]+=seconds
        with tempfile.TemporaryDirectory() as tmp:
            admission=Admission(Path(tmp)/'capacity.sqlite','https://robinhood-mainnet.g.alchemy.com/v2/offline',
                lane='pons',clock=lambda:now[0],sleeper=sleep)
            db=admission.connect()
            db.execute('UPDATE limits SET next_at=1000 WHERE endpoint=?',(admission.endpoint,))
            db.close()
            rpc=RPC(lambda current:admission.acquire('connectivity',
                getattr(current,'evidence_deadline',None),methods=['eth_chainId']))
            ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.deadline=104.25
            with patch(MODULE+'.configured_rpc',return_value=rpc):
                with self.assertRaisesRegex(BoundaryError,'provider_shared_admission_deadline'):
                    ctx.acquire(16,'pons_natural')
            self.assertIsNone(ctx.rpc)
            self.assertGreaterEqual(now[0],104.25);self.assertLess(now[0],104.31)
            db=admission.connect()
            row=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertEqual(row['deadline'],104.25);self.assertEqual(row['priority'],10)
            self.assertFalse(row['transport_attempted']);self.assertFalse(row['granted'])
            self.assertEqual(row['failure_domain'],'local_admission')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0],0)
            db.close()
        self.assertEqual(priority('connectivity'),50)

    def test_already_expired_authentication_gets_no_transport_or_wait(self):
        now=[100.0]
        with tempfile.TemporaryDirectory() as tmp:
            admission=Admission(Path(tmp)/'capacity.sqlite','https://robinhood-mainnet.g.alchemy.com/v2/offline',
                lane='pons',clock=lambda:now[0],sleeper=lambda dt:now.__setitem__(0,now[0]+dt))
            rpc=RPC(lambda current:admission.acquire('connectivity',
                getattr(current,'evidence_deadline',None),methods=['eth_chainId']))
            ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.deadline=99.0
            with patch(MODULE+'.configured_rpc',return_value=rpc):
                with self.assertRaisesRegex(BoundaryError,'provider_shared_admission_deadline'):
                    ctx.acquire(16,'pons_natural')
            self.assertEqual(now[0],100.0);self.assertIsNone(ctx.rpc)
            db=admission.connect()
            row=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertFalse(row['granted']);self.assertEqual(row['deadline'],99.0)
            self.assertFalse(row['transport_attempted']);db.close()

    def test_failed_rotation_archives_old_session_once_and_never_reuses_it(self):
        old=RPC(used=180);deadlines=[]
        def wrong_chain(current):
            deadlines.append((current.evidence_deadline,priority('connectivity')))
            raise BoundaryError('wrong_chain')
        bad=RPC(wrong_chain)
        ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.rpc=old;ctx.deadline=105.0
        with patch(MODULE+'.configured_rpc',return_value=bad):
            for _ in range(2):
                with self.assertRaisesRegex(BoundaryError,'wrong_chain'):ctx.acquire(16,'pons_natural')
                self.assertIsNone(ctx.rpc)
        self.assertEqual(ctx.completed_sessions,[old.telemetry()])
        self.assertEqual(deadlines,[(105.0,10),(105.0,10)])
        self.assertEqual(priority('connectivity'),50)
        # A separately observed later candidate has its own deadline and can retry authentication.
        ctx.deadline=111.0;good=RPC()
        with patch(MODULE+'.configured_rpc',return_value=good):self.assertIs(ctx.acquire(),good)
        self.assertEqual(good.evidence_deadline,111.0)
        self.assertEqual(ctx.completed_sessions,[old.telemetry()])

    def test_foreground_authentication_does_not_override_position_context(self):
        observed=[]
        rpc=RPC(lambda current:observed.append(priority('connectivity')))
        ctx=SelectiveEvidenceContext('https://robinhood-mainnet.g.alchemy.com/v2/offline');ctx.deadline=105.0
        @position_work
        def acquire():return ctx.acquire(16,'pons_natural')
        with patch(MODULE+'.configured_rpc',return_value=rpc):acquire()
        self.assertEqual(observed,[0]);self.assertEqual(priority('connectivity'),50)
