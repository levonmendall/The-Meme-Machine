import unittest
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.position_sessions import PositionSessions


class Rpc:
    def __init__(self,used=0,boundary=None,auth=None):
        self.used=used;self.limit=200;self.per_scope=190
        self.boundary=boundary;self.auth=auth;self.calls=[];self.verified=0
    def verify_chain(self):
        self.verified+=1
        if self.auth:raise BoundaryError(self.auth)
        self.used+=1
    def call(self,*args,**kwargs):
        if self.boundary:raise BoundaryError(self.boundary)
        if self.used>=self.limit:raise BoundaryError('provider_session_budget_exhausted')
        self.used+=1;self.calls.append((args,kwargs));return 'value'
    def batch(self,calls,**kwargs):
        if self.used+len(calls)>self.limit:raise BoundaryError('provider_session_budget_exhausted')
        return [self.call(m,p,**kwargs) for m,p in calls]
    def telemetry(self):return dict(requests=self.used)


class PositionSessionTests(unittest.TestCase):
    def test_one_operation_crosses_session_boundary_without_restarting_prior_work(self):
        old=Rpc(199);new=Rpc();events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        self.assertEqual(rpc.call('head',[],scope='monitor'),'value')
        self.assertEqual(rpc.call('quote',[],scope='monitor'),'value')
        self.assertEqual(len(old.calls),1);self.assertEqual(old.used,200)
        self.assertEqual(new.verified,1);self.assertEqual(new.used,2)
        self.assertEqual(new.calls[0][0][0],'quote')
        self.assertEqual(len(events),1);self.assertTrue(events[0][1]['authenticated'])
        self.assertEqual(new.limit,200);self.assertEqual(new.per_scope,190)

    def test_batch_retries_only_untransported_batch_once_and_retains_arguments(self):
        old=Rpc(199);new=Rpc();events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        calls=[('a',[1]),('b',[2])]
        self.assertEqual(rpc.batch(calls,scope='exit'),['value','value'])
        self.assertEqual(old.calls,[]);self.assertEqual(new.used,3)
        self.assertEqual([x[0] for x in new.calls],[('a',[1]),('b',[2])])
        self.assertEqual(events[0][1]['scope'],'exit')

    def test_fresh_session_budget_failure_is_bounded(self):
        old=Rpc(200);new=Rpc(boundary='provider_session_budget_exhausted');events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        with self.assertRaisesRegex(BoundaryError,'session_budget'):
            rpc.call('quote',[],scope='exit')
        self.assertEqual(len(events),1);self.assertEqual(new.verified,1)

    def test_provider_pressure_authentication_and_scope_budget_do_not_rotate(self):
        for reason in ('provider_rpc_429','provider_http_401','provider_pool_budget_exhausted'):
            with self.subTest(reason=reason):
                old=Rpc(boundary=reason)
                rpc=PositionSessions(old,lambda:self.fail('unexpected new session'),lambda *a:self.fail('unexpected rotation'))
                with self.assertRaisesRegex(BoundaryError,reason):rpc.call('quote',[],scope='exit')

    def test_new_session_authentication_failure_is_retained_and_fail_closed(self):
        old=Rpc(200);new=Rpc(auth='provider_http_401');events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        with self.assertRaisesRegex(BoundaryError,'401'):rpc.call('quote',[],scope='exit')
        self.assertEqual(new.calls,[]);self.assertEqual(len(events),1)
        self.assertFalse(events[0][1]['authenticated'])
        self.assertEqual(events[0][1]['boundary'],'provider_http_401')

    def test_iteration_headroom_and_configuration_bounds_remain(self):
        old=Rpc(146);new=Rpc();events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        rpc.rotate_if_needed()
        self.assertEqual(new.verified,1);self.assertEqual(events[0][1]['reason'],'iteration_headroom')
        newer=Rpc();newer.limit=201
        rpc=PositionSessions(Rpc(200),lambda:newer,lambda *a:None)
        with self.assertRaisesRegex(BoundaryError,'configuration_drift'):rpc.call('quote',[])
        self.assertEqual(newer.verified,0)

    def test_transient_replacement_authentication_retries_before_call(self):
        old=Rpc(200);new=Rpc(auth='provider_rpc_429');events=[];factories=[]
        def factory():
            factories.append(True);return new
        rpc=PositionSessions(old,factory,lambda *row:events.append(row))
        with self.assertRaisesRegex(BoundaryError,'429'):rpc.call('quote',[],scope='exit')
        self.assertEqual(new.calls,[]);self.assertEqual(new.verified,1)
        new.auth=None
        self.assertEqual(rpc.call('quote',[],scope='exit'),'value')
        self.assertEqual(new.verified,2);self.assertEqual(len(factories),1)
        self.assertEqual(events[-1][0],None)
        self.assertFalse(events[-1][1]['local_session_rotation'])
        self.assertEqual(events[-1][1]['authentication_attempt'],2)
        self.assertTrue(events[-1][1]['authenticated'])
        self.assertEqual(new.calls,[(('quote',[]),dict(scope='exit'))])

    def test_persistent_replacement_authentication_never_dispatches_reads(self):
        for reason in ('provider_rpc_429','provider_http_401'):
            with self.subTest(reason=reason):
                old=Rpc(200);new=Rpc(auth=reason);events=[];factories=[]
                def factory():
                    factories.append(True);return new
                rpc=PositionSessions(old,factory,lambda *row:events.append(row))
                with self.assertRaisesRegex(BoundaryError,reason):rpc.call('quote',[])
                for operation in (lambda:rpc.call('quote',[]),
                                  lambda:rpc.batch([('quote',[])]),
                                  rpc.rotate_if_needed):
                    with self.assertRaisesRegex(BoundaryError,reason):operation()
                self.assertEqual(new.calls,[]);self.assertEqual(new.verified,4)
                self.assertEqual(len(factories),1)
                self.assertEqual([x[1]['authentication_attempt'] for x in events],[1,2,3,4])
                self.assertTrue(all(not x[1]['authenticated'] for x in events))

    def test_iteration_retry_authenticates_same_session_before_monitor(self):
        old=Rpc(146);new=Rpc(auth='provider_rpc_429');events=[]
        rpc=PositionSessions(old,lambda:new,lambda *row:events.append(row))
        with self.assertRaisesRegex(BoundaryError,'429'):rpc.rotate_if_needed()
        new.auth=None
        rpc.rotate_if_needed()
        rpc.batch([('head',[])],scope='monitor')
        self.assertEqual(new.verified,2)
        self.assertEqual(new.calls,[(('head',[]),dict(scope='monitor'))])

    def test_explicit_chain_check_failure_invalidates_session_before_reads(self):
        old=Rpc();events=[]
        rpc=PositionSessions(old,lambda:self.fail('unexpected rotation'),lambda *row:events.append(row))
        old.auth='provider_rpc_429'
        with self.assertRaisesRegex(BoundaryError,'429'):rpc.verify_chain()
        with self.assertRaisesRegex(BoundaryError,'429'):rpc.call('quote',[])
        self.assertEqual(old.calls,[])
        old.auth=None
        self.assertEqual(rpc.call('quote',[]),'value')
        self.assertEqual(old.verified,3)
