"""Bounded native Pons SQL attribution on synthetic disposable state only."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from engineering.diagnostics.pons_query_cost import fixture,measure
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.plane import Plane,canonical
from meme_machine.runtime.robinhood.accounting import high_water,project
from meme_machine.runtime.robinhood.pons import Broker,durable_cache
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_attempts import Attempts
from meme_machine.lanes.pons.pons_natural_observation import MarketScout

SCOPE='SYNTHETIC_NATIVE_QUERY_ATTRIBUTION_ONLY_NOT_LIVE_CAPACITY'
DOMAIN='pons:shared:synthetic-offline-cost'


def index_size(db):
    result=dict(page_size=db.execute('PRAGMA page_size').fetchone()[0],
        page_count=db.execute('PRAGMA page_count').fetchone()[0])
    result['database_logical_bytes']=result['page_size']*result['page_count']
    try:
        result['indices']={name:dict(bytes=bytes,pages=pages) for name,bytes,pages in db.execute(
            "SELECT name,SUM(pgsize),COUNT(*) FROM dbstat WHERE name LIKE 'benchmark_%' GROUP BY name")}
    except sqlite3.Error:result['indices']='DBSTAT_UNAVAILABLE'
    return result


class Queries:
    def __init__(self,databases):
        self.databases=databases;self.rows={};self.current={};self.until=0

    def attach(self):
        self.until=time.monotonic()+15
        for name,db in self.databases:
            def trace(sql,name=name):
                normalized=re.sub(r"'(?:''|[^'])*'",'?',sql)
                normalized=re.sub(r'\b\d+(?:\.\d+)?\b','?',normalized)
                key=name+':'+normalized
                if key not in self.rows:
                    if len(self.rows)>=128:raise ValueError('benchmark_query_shape_bound')
                    self.rows[key]=dict(database=name,sql=normalized,calls=0,vm_steps_approx=0)
                self.rows[key]['calls']+=1;self.current[name]=key
            def progress(name=name):
                key=self.current.get(name)
                if key is not None:self.rows[key]['vm_steps_approx']+=1000
                return int(time.monotonic()>self.until)
            db.set_trace_callback(trace);db.set_progress_handler(progress,1000)

    def detach(self):
        for _,db in self.databases:
            db.set_trace_callback(None);db.set_progress_handler(None,0)


def observe(label,call,repeat,databases,*,prepare=None):
    queries=Queries(databases);samples=[]
    for _ in range(repeat):
        if prepare is not None:prepare()
        queries.attach()
        try:samples.append(measure(label,call,1))
        finally:queries.detach()
    result=dict(operation=label,repeat=repeat,
        seconds=sum(r['seconds'] for r in samples),thread_cpu_seconds=sum(r['thread_cpu_seconds'] for r in samples),
        process_io_delta={key:sum(row['process_io_delta'][key] for row in samples)
            for key in samples[0]['process_io_delta']},
        statements=sum(row['calls'] for row in queries.rows.values()),
        sqlite_vm_steps_approx=sum(row['vm_steps_approx'] for row in queries.rows.values()),
        sql_shapes=sorted(queries.rows.values(),key=lambda r:r['vm_steps_approx'],reverse=True))
    result['seconds_each']=result['seconds']/repeat
    result['reader_logical_bytes_each']=result['process_io_delta']['rchar']/repeat
    print(json.dumps(dict(operation=label,wall_each=result['seconds_each'],logical_bytes_each=result['reader_logical_bytes_each'],vm_each=result['sqlite_vm_steps_approx']/repeat)),flush=True)
    return result


def main(output):
    if sys.version_info[:3]!=(3,12,14):raise ValueError('benchmark_pinned_python_required')
    install_network_guard()
    output=Path(output).resolve()
    # Operational predicates are fixed source policy, not synthetic readiness.
    os.environ['MM_OPERATIONAL_PHASE']='OFFLINE_COST';os.environ['MM_MODE']='PAPER'
    with Scratch() as scratch:
        def audit(event,args):
            if event=='sqlite3.connect':
                value=os.fsdecode(args[0]);value=value.removeprefix('file:').split('?',1)[0]
                if not Path(value).resolve().is_relative_to(scratch.path):raise RuntimeError('benchmark_foreign_database_forbidden')
            if event=='open' and not isinstance(args[0],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                path=Path(os.fsdecode(args[0])).resolve()
                if path!=output and not path.is_relative_to(scratch.path):raise RuntimeError('benchmark_foreign_write_forbidden')
        sys.addaudithook(audit)
        now=[1001.];path=scratch.path/'plane.sqlite'
        # Construct the real Broker while empty, before adding the clearly
        # synthetic rows through the existing production-schema cost fixture.
        broker=Broker(path,'synthetic-offline-policy',clock=lambda:now[0])
        plane=broker.plane
        populated=fixture(path,1381,4096,768,4096)
        populated.close()
        with plane.transaction():
            plane.db.execute('UPDATE candidates SET interpretation=?',(canonical(broker.policy),))
            plane.db.execute('UPDATE evidence SET namespace=?',(DOMAIN+':header_number',))
            # Real header-number cache shape, still explicitly synthetic
            # provenance and never used by a qualification or financial book.
            plane.db.executemany('UPDATE evidence SET body=? WHERE namespace=? AND key=?',
                ((canonical(dict(number=hex(n),hash='0x'+f'{n:064x}',timestamp=hex(1000),synthetic=True,padding='x'*768)),DOMAIN+':header_number',str(n)) for n in range(4096)))
        peer=Plane(path,clock=lambda:now[0]);pipeline=Pipeline(scratch.path/'pipeline.sqlite','pons','synthetic-offline-policy')
        attempts=Attempts(plane);scout=MarketScout(plane);cache=durable_cache(plane,DOMAIN)
        try:
            pipeline.db.execute('PRAGMA synchronous=OFF')
            while project(plane,pipeline,through=high_water(plane))==256:scratch.check()
            pipeline.db.execute('PRAGMA synchronous=FULL')
            plane.maintain();pipeline.snapshot()
            result=dict(schema='pons-maintenance-cost-v1',scope=SCOPE,source_commit='0c8e9beae8eed6e4579f4473c4f449f711fb5691',python=sys.version,sqlite=sqlite3.sqlite_version,
                plane_source_sha256=hashlib.sha256((Path(__file__).resolve().parents[2]/'meme_machine/runtime/robinhood/plane.py').read_bytes()).hexdigest(),
                fixture=dict(candidates=1381,observations=4096,transitions=4096,evidence=4096,payload_bytes=768),
                production_population_claim=False,financial_authority=False,provider_requests=0,
                vm_scope='Approximate progress-callback steps attributed to most recently traced statement per connection; nested cursor fetches can overlap.',measurements=[])
            databases=[('plane',plane.db),('pipeline',pipeline.db)]
            def record(label,call,repeat=8,prepare=None):
                result['measurements'].append(observe(label,call,repeat,databases,prepare=prepare))
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');scratch.check()
            record('Plane.maintain unchanged',plane.maintain)
            header=[1000000]
            def add_header(owner):
                header[0]+=1;n=header[0]
                owner.put(DOMAIN+':header_number',str(n),dict(number=hex(n),hash='0x'+f'{n:064x}',timestamp=hex(1000),synthetic=True,padding='x'*768),dict(authority='SYNTHETIC_OFFLINE_FIXTURE'))
            record('Plane.maintain after local header write',plane.maintain,prepare=lambda:add_header(plane))
            record('Plane.maintain after peer header write',plane.maintain,prepare=lambda:add_header(peer))
            record('Broker.report_to unchanged',lambda:broker.report_to(pipeline))
            record('Broker.report_to after peer header write',lambda:broker.report_to(pipeline),prepare=lambda:add_header(peer))
            record('Pipeline.snapshot unchanged',pipeline.snapshot)
            record('Plane.snapshot full retained counts',lambda:plane.snapshot('pons'))
            record('Broker.rows pending materialization',lambda:broker.rows)
            record('durable_cache.numeric_tip retained headers',cache.numeric_tip)
            record('Plane.evidence_namespaces',plane.evidence_namespaces)
            # Native public observation+Broker nomination work, with fixed
            # local arrays. No transport, receipt authority or strategy result.
            counter=[2000000]
            class OfflineRpc:
                def batch(self,calls,**kwargs):
                    result=[]
                    for method,params in calls:
                        if method=='eth_getBlockByNumber':
                            block=int(params[0],16);result.append(dict(number=hex(block),hash='0x'+f'{block:064x}',timestamp=hex(int(now[0]))))
                        elif method=='eth_getLogs':
                            query=params[0];block=int(query['fromBlock'],16)
                            result.append([dict(address='0x'+f'{n+1:040x}',transactionHash='0x'+f'{block*8+n:064x}',logIndex=hex(n),transactionIndex='0x0',blockNumber=hex(block),blockHash='0x'+f'{block:064x}',topics=[scout.curve_topics[0]],data='0x') for n in range(8)])
                        else:raise ValueError('benchmark_unexpected_rpc_method')
                    return result
            rpc=OfflineRpc()
            def discover():
                counter[0]+=1;block=counter[0]
                return scout.read_market(rpc,block,block,nominate=lambda event,observed:broker.enqueue(event,now=observed))
            record('MarketScout.read_market plus 8 real Broker.enqueue',discover)
            record('Attempts.maintain unchanged clock',lambda:attempts.maintain(now[0]))
            def advance():now[0]+=61
            record('Attempts.maintain full sweep zero attempts',lambda:attempts.maintain(now[0]),prepare=advance)
            result['final_counts']={table:plane.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('candidates','observations','transitions','evidence','pons_scout_events','pons_attempts')}
            # Preserve a known excess row in this disposable fixture to expose
            # exactly the native retention read shapes. Do not run DELETE here.
            from meme_machine.runtime.operating_families import active_sql
            with plane.transaction():
                tail=plane.db.execute('SELECT MAX(seq) FROM transitions').fetchone()[0]
                plane.db.execute('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)',
                    (tail+1,'pons:synthetic:00000000',1,now[0],'watching',None,'{}','{}',canonical(dict(synthetic=True,extra_retention_row=True))))
            participating='candidate NOT IN (SELECT id FROM candidates WHERE NOT ('+active_sql('lane')+'))'
            boundary='SELECT seq FROM transitions WHERE '+participating+' ORDER BY seq DESC LIMIT 1 OFFSET ?'
            cutoff=plane.db.execute(boundary,(4095,)).fetchone()[0]
            reads=[('native_retention_boundary',boundary,(4095,)),
                ('native_retention_excess','SELECT 1 FROM transitions WHERE ('+participating+') AND seq<? LIMIT 1',(cutoff,)),
                ('native_inactive_candidates','SELECT id FROM candidates WHERE NOT ('+active_sql('lane')+')',())]
            result['read_only_index_comparators']=[]
            result['diagnostic_index_creation']=[]
            expected={label:plane.db.execute(sql,args).fetchall() for label,sql,args in reads}
            for variant in ('existing_schema','candidate_covering','candidate_and_transition_covering'):
                sql=('CREATE INDEX benchmark_candidate_lane_identity ON candidates(lane,id)' if variant=='candidate_covering' else
                    'CREATE INDEX benchmark_transition_sequence_candidate ON transitions(seq,candidate)' if variant=='candidate_and_transition_covering' else None)
                before_size=index_size(plane.db)
                if sql:
                    created=measure('create diagnostic covering index',lambda:plane.db.execute(sql),1,db=plane.db)
                    result['diagnostic_index_creation'].append(dict(variant=variant,before=before_size,after=index_size(plane.db),measurement=created))
                for label,sql,args in reads:
                    if plane.db.execute(sql,args).fetchall()!=expected[label]:raise ValueError('benchmark_index_changed_retention_selection')
                    explain=[list(row) for row in plane.db.execute('EXPLAIN QUERY PLAN '+sql,args)]
                    sample=measure(label,lambda sql=sql,args=args:plane.db.execute(sql,args).fetchall(),16,db=plane.db)
                    result['read_only_index_comparators'].append(dict(variant=variant,plan=explain,measurement=sample))
            # Compare the same native eight-event acquisition/nomination
            # workload on independent exact logical copies. Only diagnostic
            # covering indices differ; no production schema is changed.
            plane.db.execute('DROP INDEX benchmark_transition_sequence_candidate')
            plane.db.execute('DROP INDEX benchmark_candidate_lane_identity')
            result['native_index_comparators']=[]
            compared_outputs=[]
            for variant in ('existing_schema','candidate_covering','candidate_and_transition_covering'):
                cloned=scratch.path/(variant+'.sqlite')
                with closing(sqlite3.connect(cloned)) as target:plane.db.backup(target)
                cloned_broker=Broker(cloned,'synthetic-offline-policy',clock=lambda:now[0])
                try:
                    cp=cloned_broker.plane;cs=MarketScout(cp);counter[0]=2000008
                    if variant!='existing_schema':cp.db.execute('CREATE INDEX benchmark_candidate_lane_identity ON candidates(lane,id)')
                    if variant=='candidate_and_transition_covering':cp.db.execute('CREATE INDEX benchmark_transition_sequence_candidate ON transitions(seq,candidate)')
                    def copied_discover():
                        counter[0]+=1;block=counter[0]
                        return cs.read_market(rpc,block,block,nominate=lambda event,observed:cloned_broker.enqueue(event,now=observed))
                    sample=observe('same native 8-event batch',copied_discover,8,[('plane',cp.db)])
                    logical={table:[list(row) for row in cp.db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                        for table in ('candidates','observations','transitions','pons_current_watch','pons_scout_events','runtime')}
                    logical_hash=hashlib.sha256(canonical(logical).encode()).hexdigest();compared_outputs.append(logical_hash)
                    result['native_index_comparators'].append(dict(variant=variant,measurement=sample,logical_output_sha256=logical_hash))
                    output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');scratch.check()
                finally:cloned_broker.close()
            if len(set(compared_outputs))!=1:raise ValueError('benchmark_index_changed_native_output')
            output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
            scratch.check();scratch.success=True
        finally:
            pipeline.close();peer.close();broker.close()
    print(json.dumps(dict(state='COMPLETE',output=str(output))))


if __name__=='__main__':main(sys.argv[1])
