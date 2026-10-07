"""Run production source, owner, RPCs, EDF and position reads on disposable state.

No PaperBook, portfolio, entry, signature or submission is instantiated. The
meter delegates unchanged requests to urllib: it does not supply a benchmark
provider. Every physical call still passes the production Governor decorator.
"""
import argparse,asyncio,contextlib,contextvars,datetime,hashlib,json,os,resource,shlex,sqlite3,struct,tempfile,threading,time,traceback,urllib.request,zlib
from concurrent.futures import ThreadPoolExecutor
from collections import Counter,defaultdict
from pathlib import Path

FAMILY=contextvars.ContextVar('certification_family',default='shared')
CU={'getGenesisHash':10,'getSlot':20,'getMultipleAccounts':20,'getAccountInfo':10,'getBlockTime':20,'getTokenLargestAccounts':20,'getProgramAccounts':20,'getProgramAccountsV2':20,'getTransactionsForAddress':100,'getTransaction':40,'getBlock':40,'getSignaturesForAddress':40}
POSITIVE='E1XdfKcKbE6uyamZy3fy4T9YBBKotAZp1ky6s1FMoxED'
PUMP='4oNG2rkpvuswaA7MVdHDXw8oDPrmUzyMmNMpntd9pump'
SWAP_MINT='B3LhYoi2KevfieaChouDSK5c8jBHuXd4abCrwFJdpump'

def environment(path):
    allowed={'MM_SOLANA_READ_RPC_URL','MM_SOLANA_YELLOWSTONE_TOKEN','ALCHEMY_SOLANA_RPC_URL'};out={}
    for line in Path(path).read_text().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):continue
        key,value=line.removeprefix('export ').split('=',1)
        if key in allowed:
            parsed=shlex.split(value,comments=True)
            if parsed:out[key]=parsed[0]
    return out

def safe_reason(error):
    import re
    message=str(error)
    return message if re.fullmatch(r'[a-z][a-z0-9_:, ]{0,160}',message) else type(error).__name__

def quantiles(values):
    a=sorted(values)
    if not a:return dict(N=0,p50=None,p95=None,p99=None,max=None)
    def q(p):return a[min(len(a)-1,int((len(a)-1)*p))]
    return dict(N=len(a),p50=q(.5),p95=q(.95),p99=q(.99),max=a[-1])

class Meter:
    def __init__(self,out):
        self.out=out;self.lock=threading.Lock();self.rows=[];self.raw=Counter();self.errors=Counter();self.original=urllib.request.urlopen
        self.archive=(out/'http.ndjson').open('w');self.started=time.time();self.active=0;self.peak_concurrency=0
    def open(self,request,*args,**kw):
        payload=json.loads(request.data) if hasattr(request,'data') and request.data else None
        calls=payload if isinstance(payload,list) else [payload]
        if any(not isinstance(c,dict) or c.get('method') not in CU for c in calls):
            raise ValueError('certification_read_only_method_required')
        start=time.time();family=FAMILY.get();methods=[c['method'] for c in calls]
        with self.lock:self.active+=1;self.peak_concurrency=max(self.peak_concurrency,self.active)
        try:response=self.original(request,*args,**kw)
        except Exception as exc:
            with self.lock:self.errors[type(exc).__name__]+=1;self.active-=1
            raise
        meter=self
        class Response:
            def __enter__(self):response.__enter__();return self
            def __exit__(self,*v):
                with meter.lock:meter.active-=1
                return response.__exit__(*v)
            def __getattr__(self,key):return getattr(response,key)
            def read(self,*a,**k):
                raw=response.read(*a,**k);finished=time.time()
                try:decoded=json.loads(raw)
                except (ValueError,UnicodeDecodeError):
                    decoded=dict(invalid_JSON_SHA256=hashlib.sha256(raw).hexdigest())
                    with meter.lock:meter.errors['invalid_JSON']+=1
                if isinstance(decoded,dict) and 'error' in decoded:
                    code=decoded['error'].get('code')
                    with meter.lock:meter.errors['RPC_'+str(code)]+=1
                archive_bodies=0
                if 'getTransactionsForAddress' in methods:
                    result=decoded.get('result',{})
                    if isinstance(result,dict):archive_bodies=sum('transaction' in t for t in result.get('data',[]))
                row=dict(family=family,methods=methods,calls=len(calls),cu=sum(CU[m] for m in methods),bytes=len(raw),started=start,finished=finished,seconds=finished-start,
                    account_fetches=sum(len(c.get('params',[[]])[0]) for c in calls if c['method']=='getMultipleAccounts'),transaction_bodies=methods.count('getTransaction'),scoped_archive_bodies=archive_bodies,blocks=methods.count('getBlock'))
                with meter.lock:
                    meter.rows.append(row);meter.raw[family]+=len(raw)
                    meter.archive.write(json.dumps(dict(**row,requests=calls,response=decoded))+'\n');meter.archive.flush()
                return raw
        return Response()
    def install(self):urllib.request.urlopen=self.open
    def close(self):urllib.request.urlopen=self.original;self.archive.close()
    def totals(self):
        with self.lock:return dict(calls=sum(r['calls'] for r in self.rows),cu=sum(r['cu'] for r in self.rows),http_bytes=sum(r['bytes'] for r in self.rows),transaction_bodies=sum(r['transaction_bodies'] for r in self.rows),scoped_archive_bodies=sum(r['scoped_archive_bodies'] for r in self.rows),blocks=sum(r['blocks'] for r in self.rows),errors=dict(self.errors),peak_http_concurrency=self.peak_concurrency)

class Certification:
    def __init__(self,out,seconds,env):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.runtime.governor import Governor
        from meme_machine.runtime.evidence_worker import RepairRPC
        from meme_machine.solana_selective_source import SelectiveSource
        self.out=out;self.seconds=seconds;self.env=env;self.config=AlchemyEndpoint.parse(env['MM_SOLANA_READ_RPC_URL'])
        self.governor=Governor(out/'governor.sqlite');self.rpc=RepairRPC(self.config.http_url,self.governor)
        self.source=SelectiveSource(self.config,self.rpc,token=env.get('MM_SOLANA_YELLOWSTONE_TOKEN',self.config.credential))
        native_measured=self.source.measured_rpc
        async def labeled_rpc(method,params,family,priority=4):
            token=FAMILY.set(family+'_source')
            try:return await native_measured(method,params,family,priority)
            finally:FAMILY.reset(token)
        self.source.measured_rpc=labeled_rpc
        from .transport_meter import TransportMeter
        self.transport=TransportMeter(out/'provider.frames.zlib');self.source.observer=self.transport
        self.family_context=FAMILY;self.pump_candidates=None
        self.meter=Meter(out);self.latencies=defaultdict(list);self.results=[];self.position=[];self.monitor=[];self.errors=[];self.work=None;self.stop=None;self.worker_stop=threading.Event();self.cpu0=time.process_time();self.wall0=time.time()
        source_paths=['meme_machine/solana_selective_source.py','meme_machine/solana_selective_history.py','meme_machine/solana_scoped_retirement.py','meme_machine/solana_candidate_lifecycle.py','meme_machine/solana_candidate_join.py','meme_machine/solana_stable_shards.py','meme_machine/runtime/governor.py','meme_machine/runtime/solana_warming.py','meme_machine/runtime/candidate_history.py','meme_machine/runtime/lifecycle_timing.py','meme_machine/runtime/evidence_worker.py','meme_machine/lanes/meteora/runner.py','meme_machine/lanes/pump/solana_evidence_runtime.py','engineering/solana_capacity/certify.py','engineering/solana_capacity/pump_candidates.py','engineering/solana_capacity/transport_meter.py']
        self.source_hashes={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source_paths};self.position_pacer={};self.position_rpcs={};self.position_states={};self.pump_mint=PUMP;self.pump_choices=[];self.attempts=[]
    async def request(self,fn,priority=1):return await self.work(fn,priority)
    def state(self,s):
        from meme_machine.solana_selective_source import install
        h=install(s);db=s.writer.db
        return dict(at=time.time(),observations=dict(db.execute('SELECT family,COUNT(*) FROM market_observations GROUP BY family')),
          lifecycle=dict(db.execute('SELECT state,COUNT(*) FROM candidate_lifecycle GROUP BY state')),
          promotions=[dict(id=i,family=f,address=a,created=t,body=json.loads(b)) for i,f,a,b,t in db.execute("SELECT id,family,address,body,created FROM candidate_history_outbox WHERE kind='promotion'")],
          delivery=[dict(family=f,transport=t,bytes=b,cu=c,calls=n) for f,t,b,c,n in db.execute('SELECT family,transport,SUM(raw_bytes),SUM(rpc_cu),SUM(calls) FROM provider_delivery GROUP BY family,transport')],
          source_checkpoint_count=db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],
          outbox_pending=db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],
          gaps=db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE repaired IS NULL').fetchone()[0],
          canonical_events=db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0])
    async def __call__(self,work,stop):
        from meme_machine.solana_selective_source import install
        from meme_machine.solana_selective_history import FAMILIES
        from meme_machine.lanes.pump.postgrad import pumpswap_pool
        self.work=work;self.stop=stop;self.started=time.time();self.cutoff=self.started+self.seconds
        # Same durable service-interest command used by real position controllers.
        tip=await asyncio.to_thread(self.rpc.call,'getSlot',[dict(commitment='finalized')],True)
        # One bounded latest-transaction locator seeds the real lower-bound
        # witness required by the position reader. Its interval is then proved
        # by the ordinary ascending archive worker; the locator proves no gap.
        latest=await asyncio.to_thread(self.rpc.call,'getTransactionsForAddress',[POSITIVE,dict(transactionDetails='full',sortOrder='desc',limit=1,commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,filters=dict(slot=dict(gte=0,lte=tip)))],True)
        last_slot=latest['data'][0]['slot'] if latest.get('data') else max(1,tip-32)
        def seed(s):
            h=install(s);h.bind('meteora',POSITIVE);return h.request('meteora',POSITIVE,last_slot,tip,priority=0,deadline=time.time()+150)
        await work(seed,0)
        for family,address in [('pump',PUMP),('pumpswap',pumpswap_pool(SWAP_MINT)),('meteora',POSITIVE)]:
            def pin(s,f=family,a=address):
                install(s);return s.fence.command(dict(op='interest',owner='capacity:position:'+f,scope=FAMILIES[f],lower_slot=last_slot if f=='meteora' else max(1,tip-32),addresses=[a],lifecycle='open',priority=0,evidence_class='transactions' if f=='meteora' else 'logs'))
            await work(pin,0)
        tasks=[asyncio.create_task(self.source.run(work,stop))]
        for family in ('pump','pumpswap','meteora'):tasks.append(asyncio.create_task(self.position_loop(family)))
        tasks.append(asyncio.create_task(self.candidate_loop()))
        tasks.append(asyncio.create_task(self.pump_candidate_loop()))
        try:
            drain_until=self.cutoff+150
            while time.time()<drain_until and not stop.is_set():
                for n,t in enumerate(tasks):
                    if t.done():
                        try:t.result()
                        except Exception as e:self.errors.append(dict(task=n,type=type(e).__name__,reason=safe_reason(e),frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(e.__traceback__)]))
                        stop.set();break
                if stop.is_set():break
                snapshot=await work(self.state,3);snapshot['provider']=self.governor.status();snapshot['rpc']=self.meter.totals()
                snapshot['position_ready_counts']=dict(Counter(r['family'] for r in self.position if r['ready']));snapshot['position_errors']=dict(Counter(r.get('reason','') for r in self.position if not r['ready']));snapshot['cpu_seconds']=time.process_time()-self.cpu0;snapshot['rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                try:
                    with sqlite3.connect(self.out/'candidate.sqlite') as db:
                        snapshot['work']=dict(db.execute('SELECT status,COUNT(*) FROM work GROUP BY status'))
                        snapshot['warming']=db.execute("SELECT COUNT(*),MIN(created_at),MIN(deadline) FROM work WHERE status='pending'").fetchone()
                        cohort_debt=db.execute("SELECT COUNT(*) FROM work WHERE status IN ('pending','active') AND created_at<=?",(self.cutoff,)).fetchone()[0]
                except sqlite3.Error:pass
                self.monitor.append(snapshot)
                if len(self.monitor)%5==0:
                    (self.out/'progress.json').write_text(json.dumps(dict(seconds=time.time()-self.started,**snapshot),indent=2)+'\n')
                    print(json.dumps(dict(seconds=round(time.time()-self.started,1),observations=snapshot['observations'],promotions=len(snapshot['promotions']),rpc=snapshot['rpc'],work=snapshot.get('work'),errors=self.errors)),flush=True)
                # Payload plus a framing allowance; stop well before the $5 cap.
                cost=snapshot['rpc']['cu']*.525/1e6+sum(r['bytes']*(75/1e12 if r['transport']=='yellowstone' else .0002*.525/1e6 if r['transport']=='websocket' else 0) for r in snapshot['delivery'])
                if cost>4.0:self.errors.append(dict(reason='diagnostic_budget_stop'));stop.set();break
                if time.time()>=self.cutoff and cohort_debt==0:break
                await asyncio.sleep(1)
        finally:
            self.worker_stop.set();stop.set()
            # Source and threaded native reads retain the real governor deadlines.
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            self.final=await work(self.state,0);self.ended=time.time()
    def native_rpc(self,family,deadline=None):
        if family=='meteora':
            from meme_machine.lanes.meteora import dlmm_alchemy_provider as native
            pacer=native.AlchemyPacer()
        else:
            from meme_machine.lanes.pump import solana_read_rpc as native
            pacer=native.SolanaReadPacer()
        rpc=native.new_rpc(limit=240,pacer=pacer);rpc.evidence_priority=30
        if deadline is not None:rpc.evidence_deadline=deadline
        return rpc,pacer
    def position_tick(self,family):
        from meme_machine.runtime.request_scheduling import priority
        from meme_machine.lanes.pump.provider import PumpAdapter
        from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,graduation_handoff,sell_quote
        from meme_machine.lanes.pump import pump
        from meme_machine.lanes.pump.pump_acceleration_strategy import ExitObservation,exit_decision,MODE_LATE_CURVE,MODE_POSTGRAD
        from meme_machine.lanes.meteora import dlmm,runner
        token=priority.set(0);ft=FAMILY.set(family+'_position');start=time.time();before=len(self.meter.rows)
        try:
            if family not in self.position_rpcs or self.position_rpcs[family].calls>200:
                rpc,pacer=self.native_rpc(family);self.position_rpcs[family]=rpc;self.position_pacer[family]=pacer
            rpc=self.position_rpcs[family]
            if family=='pump':
                with sqlite3.connect(os.environ['MM_SOLANA_CANDIDATE_HISTORY_DB']) as db:
                    choices=[r[0] for r in db.execute("SELECT candidate FROM events WHERE kind='pump_create' ORDER BY slot DESC LIMIT 40")]
                for mint in choices:
                    if mint not in self.pump_choices:self.pump_choices.append(mint)
                if self.pump_choices and self.position_states.get('pump_illiquid'):
                    self.pump_mint=self.pump_choices.pop(0);self.position_states.pop('pump_illiquid',None)
                snap=PumpAdapter(rpc).snapshot(self.pump_mint,int(time.time()),True);curve=pump.curve(snap['accounts'][0]);supply,_=pump.mint_info(snap['accounts'][1]);fee=pump.fees(snap['accounts'][2],curve,supply);value,_=pump.sell(curve,1_000_000_000,fee);safety=curve.complete
                from meme_machine.lanes.pump.runner import ConcentrationReader
                reader=self.position_states.get('pump_concentration')
                if reader is None or reader.primary is not rpc:
                    reader=ConcentrationReader(rpc);self.position_states['pump_concentration']=reader
                concentration,_=reader.read(self.pump_mint,snap,priority=True)
            elif family=='pumpswap':
                adapter=PostGraduationAdapter(rpc)
                from meme_machine.lanes.pump.pumpswap_survivor_evidence import SOL_USD_ACCOUNT,sol_usd_lower_micros
                from meme_machine.lanes.pump.runner import _postgrad_concentration
                graduation=adapter.graduation_snapshot(SWAP_MINT,int(time.time()),True)
                handoff=graduation_handoff(graduation,int(time.time()))
                snap=adapter.pumpswap_snapshot(handoff,int(time.time()),True,additional_accounts=(SOL_USD_ACCOUNT,))
                quote=sell_quote(snap,1_000_000_000);value=quote.output_amount;safety=False
                concentration=_postgrad_concentration(rpc,snap)
                usd=sol_usd_lower_micros(snap['additional_accounts'][SOL_USD_ACCOUNT],now=int(time.time()),slot=snap['slot'])
            else:
                adapter=dlmm.Adapter(rpc,network_verified=True)
                current=self.position_states.get('meteora_state')
                if current is None:
                    snap=adapter.snapshot(POSITIVE,int(time.time()),True,True);current=dlmm.validate(snap,int(time.time()),'real')
                    # Existing position valuation geometry from authenticated parity.
                    vector=json.loads(Path('engineering/solana_closure/positive_parity.json').read_text())['minimal_vector']
                    position=runner._build_position(current,vector,runner.load_policy())
                    self.position_states['meteora_state']=current
                    self.position_states['meteora_origin']=current
                    self.position_states['meteora_position']=position
                    self.position_states['meteora_features']=vector
                    return dict(family=family,ready=False,bootstrap=True,seconds=time.time()-start)
                # Actual native capture/reconstruction/flow/fee/mark/safety path.
                tape,cursor,census=runner._capture_chunk(adapter,current,[current['slot'],2**31-1,2**31-1],1)
                final=tape.terminal;features=self.position_states['meteora_features'];policy=runner.load_policy()
                self.position_states['meteora_position']=runner._advance_position(self.position_states['meteora_position'],tape)
                reasons,recent,mark,uplift=runner._segment_exit(self.position_states['meteora_position'],current,tape,final,{k:features[k] for k in ('volume_rate_sol_lamports_per_second','fee_density')},policy)
                streaks=self.position_states.setdefault('meteora_confirmations',dict(volume_collapse=0,fee_density_collapse=0))
                for reason in streaks:streaks[reason]=streaks[reason]+1 if reason in reasons else 0
                confirmed=runner._eligible_exit_reasons(reasons,elapsed_seconds=int(time.time()-self.started),collapse_streaks=streaks,policy=policy)
                self.position_states['meteora_settlement']=runner._withdraw(self.position_states['meteora_position'])
                self.position_states['meteora_state']=final;value=mark;exit_result=confirmed;safety=reasons;snap=dict(slot=final['slot'])
            if family!='meteora':
                self.position_states.setdefault(family+'_basis',value);self.position_states[family+'_hwm']=max(value,self.position_states.get(family+'_hwm',0));basis=max(1,self.position_states[family+'_basis'])
                exit_result=exit_decision(ExitObservation(MODE_LATE_CURVE if family=='pump' else MODE_POSTGRAD,100+int(time.time()-self.started),100,int((value/basis-1)*10000),int((self.position_states[family+'_hwm']/basis-1)*10000),100,'pump.fun' if family=='pump' else 'pumpswap',graduated=safety))
                dependency=self.position_dependencies(family,snap,concentration,value)
            else:dependency=dict(ordered_history_ready=True,confirmation_state_ready=True,settlement_prerequisites_ready=True)
            rows=[r for r in self.meter.rows[before:] if r['family']==family+'_position'];elapsed=time.time()-start
            return dict(family=family,ready=True,started=start,finished=time.time(),seconds=elapsed,slot=snap['slot'],bytes=sum(r['bytes'] for r in rows),cu=sum(r['cu'] for r in rows),calls=sum(r['calls'] for r in rows),mark=value,exit=exit_result,safety=safety,settlement_accounts=True,dependencies=dependency)
        finally:priority.reset(token);FAMILY.reset(ft)
    def position_dependencies(self,family,snapshot,concentration,proceeds):
        """Exercise native history/requalification facts without a capital book.

        Missing lineage or coverage is recorded, never replaced with fabricated
        graduation times, favourable facts or economic qualification.
        """
        from types import SimpleNamespace
        from meme_machine.lanes.pump import runner
        from meme_machine.runtime.candidate_history import open_candidate_history
        mint=snapshot['mint'];now=int(time.time())
        try:
            plane=self.position_states.get(family+'_plane')
            if plane is None:
                plane=runner.RuntimeEvidence(owner='capacity:position-dependencies:'+family)
                self.position_states[family+'_plane']=plane
            confirmations=self.position_states.setdefault('position_confirmations',runner.ConfirmationBook.from_files())
            if family=='pump':
                tape=runner.LocalPumpTape(plane);creation=tape.creation(mint)
                if creation is None:raise ValueError('position_creation_history_missing')
                confirmations.observe_creation(creation)
                events=tape.window(mint,snapshot['market_time'],max_slot=snapshot['slot'])
                signal,_,_=runner._late_signal(creation,events,snapshot,concentration,confirmations)
            else:
                with contextlib.closing(open_candidate_history()) as history:
                    economic=[r['payload'] for r in history.events('pump',mint)]
                creation=next((e for e in economic if e.get('event_type')=='create'),None)
                graduation=next((e for e in economic if e.get('event_type')=='migration'),None)
                if creation is None or graduation is None:raise ValueError('position_pregraduation_history_missing')
                confirmations.observe_creation(creation);confirmations.observe_graduation(mint,graduation['market_time'])
                history=runner.LocalPumpHistory(plane,snapshot['pool'],graduation['market_time']);history.bind_snapshot(snapshot)
                state=dict(mint=mint,pool=snapshot['pool'],creation=creation,
                    graduation_time=graduation['market_time'],graduation_price=None,
                    pregrad_wallets={e['wallet'] for e in economic if e.get('wallet') and e.get('event_type')=='trade' and e['market_time']<=graduation['market_time']},history=history)
                events=runner._refresh_pool_events(state,SimpleNamespace(plane=plane),now,research=False,hydration_kind='position_monitor')
                signal,_=runner._volume_price_signal(state,snapshot,events,runner.MODE_POSTGRAD,concentration,confirmations)
            qualified=runner.qualify(signal)
            life=SimpleNamespace(position=SimpleNamespace(basis_quote_units=max(1,self.position_states[family+'_basis']),
                mint=mint,surface='pump.fun' if family=='pump' else 'pumpswap',demand_deterioration_streak=0,exit_reason=None))
            facts=runner._pump_continuation_facts(life,signal,qualified,snapshot,proceeds,now)
            capacity,_=runner._capacity(snapshot,signal.authenticated_recent_turnover,intended=1_000_000)
            return dict(ordered_history_ready=True,qualification=qualified.qualified,
                continuation_facts=facts,staged_add_execution_requalified=capacity.final_size>0)
        except Exception as exc:
            return dict(ordered_history_ready=False,qualification=False,reason=safe_reason(exc))
    async def position_loop(self,family):
        cadence=1 if family=='meteora' else 5;due=time.time()
        while not self.stop.is_set():
            await asyncio.sleep(max(0,due-time.time()));due+=cadence
            start=time.time()
            try:row=await asyncio.to_thread(self.position_tick,family)
            except Exception as e:
                if family=='pump':self.position_states['pump_illiquid']=True
                row=dict(family=family,ready=False,seconds=time.time()-start,error=type(e).__name__,reason=safe_reason(e))
            row['requested']=start;row['schedule_lateness_seconds']=max(0,start-(due-cadence));self.position.append(row)
            if family=='pump' and row['ready']:
                from meme_machine.solana_selective_source import install
                from meme_machine.solana_selective_history import FAMILIES
                def pin_current(s):
                    install(s)
                    return s.fence.command(dict(op='interest',owner='capacity:position:pump',scope=FAMILIES['pump'],lower_slot=max(1,row['slot']-32),addresses=[self.pump_mint],lifecycle='open',priority=0,evidence_class='logs'))
                if self.position_states.get('pump_pinned')!=self.pump_mint:
                    await self.work(pin_current,0);self.position_states['pump_pinned']=self.pump_mint
            if row['ready']:self.latencies[family+'_position'].append(row['seconds'])
            if time.time()>due+cadence:due=time.time()
    def evaluate_meteora(self,job):
        from meme_machine.lanes.meteora import runner
        from meme_machine.runtime.lifecycle_timing import install_meteora
        install_meteora(runner)
        item=dict(job['payload']['candidate'],_candidate_work_id=job['id']);start=time.time();ft=FAMILY.set('meteora_hydration');rpc,pacer=self.native_rpc('meteora',job['deadline']);rpcs=[rpc];adapter=runner.dlmm.Adapter(rpc,network_verified=True)
        result=dict(candidate=job['candidate'],lane='meteora',id=job['id'],first_observed=item['signal_observed_at'],original_decision_deadline=job['deadline'],queue_entry=job['created_at'],worker_claim=start,hydration_start=start,
            feasible_when_queued=None,isolated_positive_unit_fits_queue_slack=job['deadline']>job['created_at']+16.003484838,full_hydration=False)
        before=len(self.meter.rows)
        try:
            state=runner._candidate_compatibility_start(adapter,item);result['compatible']=True
            deadline=time.monotonic()+max(0,job['deadline']-time.time())
            alignment,warm,entry,origin,adapter,candidate=runner._triggered_warmup(adapter,item,state,runner.load_policy(),pacer,rpcs,deadline,None)
            result['alignment']=alignment
            result['full_hydration_required']=bool(alignment.get('trigger',{}).get('triggered'))
            if warm is not None:
                result['full_hydration']=True;result['hydration_class']='ACCOUNT_PLUS_NATIVE_TAPE'
                if alignment.get('aligned'):
                    vector=runner.pre_entry_features(origin,warm,entry,candidate,runner.load_policy());result['qualification']=runner.qualify(vector,runner.load_policy())
            elif result['full_hydration_required']:result['hydration_class']='ACCOUNT_PLUS_NATIVE_TAPE'
            elif alignment.get('reason')=='campaign_window_insufficient_preentry_time':result['hydration_class']='DEADLINE_INSUFFICIENT'
            else:result['hydration_class']='ACCOUNT_ONLY_HYDRATION'
        except runner.WarmingDeferred:
            result.update(compatible=True,hydration_class='ACCOUNT_ONLY_HYDRATION',pending_trigger=True)
        except Exception as e:
            reason=safe_reason(e)
            structural=isinstance(e,ValueError) and reason.startswith(('dlmm_unsupported_','dlmm_freeze_authority_','dlmm_native_decimals_or_program','dlmm_structural_wsol_pair_scope'))
            result.update(compatible=False if structural else None,hydration_class='INCOMPATIBLE_STRUCTURAL' if structural else 'OTHER_EXPLICIT_CLASS',error=type(e).__name__,reason=reason)
        finally:
            result.update(hydration_finish=time.time(),qualification_ready=time.time(),deadline_margin=job['deadline']-time.time(),seconds=time.time()-start)
            rows=[r for r in self.meter.rows[before:] if r['family']=='meteora_hydration'];result.update(calls=sum(r['calls'] for r in rows),cu=sum(r['cu'] for r in rows),bytes=sum(r['bytes'] for r in rows),bodies=sum(r['transaction_bodies'] for r in rows),blocks=sum(r['blocks'] for r in rows));FAMILY.reset(ft)
        return result
    async def candidate_loop(self):
        from meme_machine.runtime.candidate_history import CandidateHistory,CandidateDeadlineMissed
        # Same lane claims and EDF ordering as the production native runner.
        history=CandidateHistory(self.out/'candidate.sqlite')
        def runner_health():
            from meme_machine.lanes.meteora import runner
            try:return runner._evidence_plane().health('program:meteora')['usable']
            except Exception:return False
        try:
            while not self.stop.is_set():
                # The native runtime's admission gate is authoritative; startup
                # backlog is a recoverable observation state, not incompatibility.
                if not runner_health():await asyncio.sleep(.05);continue
                try:job=history.claim('capacity:meteora',lane='meteora')
                except CandidateDeadlineMissed as e:
                    self.results.append(dict(id=e.work['id'],candidate=e.work['candidate'],lane='meteora',hydration_class='DEADLINE_INSUFFICIENT',feasible_when_queued=None,deadline_missed=True,
                        first_observed=e.work['created_at'],queue_entry=e.work['created_at'],original_decision_deadline=e.work['deadline'],
                        reason='original_deadline_expired_before_worker_claim; individual_service_feasibility_unproven'));continue
                if job is None:await asyncio.sleep(.05);continue
                result=await asyncio.to_thread(self.evaluate_meteora,job);self.attempts.append(result)
                if result.get('pending_trigger'):continue
                if result.get('error')=='EvidenceUnavailable':
                    result['hydration_class']='OTHER_EXPLICIT_CLASS';result['compatible']=None
                    history.complete(job['id'],status='deferred',details=dict(certification=result,delay_seconds=.25))
                    continue
                self.results.append(result);history.complete(job['id'],details=dict(certification=result))
                self.latencies['meteora_hydration'].append(result['seconds']);self.latencies['meteora_qualification'].append(result['qualification_ready']-result['first_observed'])
        finally:history.close()
    async def pump_candidate_loop(self):
        from .pump_candidates import PumpCandidates
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-pump-observation')
        loop=asyncio.get_running_loop()
        self.pump_candidates=await loop.run_in_executor(executor,PumpCandidates,self)
        try:
            while not self.stop.is_set():
                await loop.run_in_executor(executor,self.pump_candidates.tick)
                await asyncio.sleep(.25)
        finally:
            await loop.run_in_executor(executor,self.pump_candidates.close)
            executor.shutdown(wait=False)
    def write(self):
        end=getattr(self,'ended',time.time());duration=end-getattr(self,'started',self.wall0)
        result=dict(schema='actual-shared-provider-certification-v1',source_sha256=self.source_hashes,classification='MEASURED_LIVE',started_UTC=datetime.datetime.fromtimestamp(self.wall0,datetime.timezone.utc).isoformat(),window_seconds=duration,planned_seconds=self.seconds,measurement_started=getattr(self,'started',self.wall0),measurement_cutoff=getattr(self,'cutoff',None),drain_seconds=max(0,duration-self.seconds),endpoint_identity=self.config.identity,worker_capacity=2,governor_interval_seconds=self.governor.solana_interval,position_equivalence='Native adapters, quote/exit/mark and DLMM tape functions through the same physical governor; no monetary controller',rpc=self.meter.totals(),final=getattr(self,'final',{}),promotions=self.results,positions=self.position,latency={k:quantiles(v) for k,v in self.latencies.items()},transport=self.transport.summary(),provider_delivery_latency={k:quantiles(v) for k,v in self.transport.latencies.items()},pump_candidate_work=[] if self.pump_candidates is None else self.pump_candidates.rows,pump_candidate_boundaries=[] if self.pump_candidates is None else self.pump_candidates.errors,errors=self.errors,monitor=self.monitor,attempts=self.attempts,pump_position_mint=self.pump_mint,cpu_seconds=time.process_time()-self.cpu0,rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        (self.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(window_seconds=duration,rpc=result['rpc'],promotions=len(self.results),position_samples=len(self.position),errors=self.errors)),flush=True)

async def main(args):
    from meme_machine.solana_evidence_service import serve
    from meme_machine.lanes.meteora import runner
    from meme_machine.solana_evidence_runtime import RuntimeEvidence
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);env=environment(args.env)
    for key,value in env.items():os.environ[key]=value
    state=Path(tempfile.mkdtemp(prefix='mm-cert-'));plane_path=state/'canonical.sqlite'
    (out/'state').symlink_to(state,target_is_directory=True)
    os.environ.update(MM_PROVIDER_GOVERNOR_DB=str(out/'governor.sqlite'),MM_SOLANA_EVIDENCE_PLANE_DB=str(plane_path),MM_SOLANA_CANDIDATE_HISTORY_DB=str(out/'candidate.sqlite'))
    c=Certification(out,args.seconds,env);c.meter.install();stop=asyncio.Event()
    try:
        from meme_machine.runtime.candidate_history import open_candidate_history
        runner.CANDIDATE_HISTORY=open_candidate_history()
        runner.EVIDENCE_PLANE=RuntimeEvidence(plane_path,owner='capacity:meteora')
        await asyncio.to_thread(c.rpc.validate_network)
        await serve(plane_path,c.config.http_url,repair_rpc=c.rpc,stop=stop,source_driver=c)
    except Exception as e:c.errors.append(dict(task='service',type=type(e).__name__,reason=safe_reason(e),errno=getattr(e,'errno',None),maintenance_failure=getattr(e,'maintenance_failure',None),frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(e.__traceback__)]))
    finally:
        stop.set();c.worker_stop.set();c.write();c.meter.close();c.transport.close()
        if runner.EVIDENCE_PLANE:runner.EVIDENCE_PLANE.close()
        for name in ('http.ndjson',):
            path=out/name
            if path.exists():path.with_suffix(path.suffix+'.zlib').write_bytes(zlib.compress(path.read_bytes(),6));path.unlink()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=1200);p.add_argument('--env',default='/etc/meme-machine/paper.env');args=p.parse_args()
    if not 10<=args.seconds<=1200:raise SystemExit('certification_window_bound')
    asyncio.run(main(args))
