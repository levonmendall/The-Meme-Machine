"""Offline SQLite statement-lifetime probe; no provider calls."""
from dataclasses import replace
from pathlib import Path
import json,re,sqlite3,tempfile,traceback
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run381_retention_progress import record

def normalized(sql):
 return re.sub(r"'(?:''|[^'])*'|\b\d+\b","?",sql)[:400]
def operation(state,name):
 if name=='archive':return state.writer.archive_snapshot(1000)
 if name=='retain':return state.writer.retain(1000,archive_first=False)
 if name=='health':return state.maintenance_health({})
 raise AssertionError(name)
def seed(path,archived):
 state=ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
 rows=[replace(record(),scope=scope,identity=scope+':'+str(i),payload={'raw_lineage':{'logs':['log'*100]*20}}) for scope in ('a','b') for i in range(40)]
 state.writer.ingest(rows)
 if archived:state.writer.archive(1000)
 return state
results=[]
for archived in (False,True):
 for name in ('archive','retain','health'):
  with tempfile.TemporaryDirectory() as td:
   state=seed(Path(td)/'db',archived);sql=[]
   state.writer.db.set_trace_callback(lambda text:sql.append(normalized(text)))
   operation(state,name);state.writer.db.set_trace_callback(None);state.writer.close()
  targets=list(dict.fromkeys(sql))
  for target in targets:
   for instruction_budget in (1,10,100,1000):
    with tempfile.TemporaryDirectory() as td:
     state=seed(Path(td)/'db',archived);armed=False;interrupted=False;progress_calls=0;last=None;held=[]
     def trace(sql):
      global armed,last
      last=normalized(sql)
      if last==target:armed=True
     def progress():
      global interrupted,progress_calls
      if armed and not interrupted and not getattr(state.writer,'_retention_atomic',False):
       progress_calls+=1
       if progress_calls>=instruction_budget:interrupted=True;return 1
      return 0
     state.writer.db.set_trace_callback(trace);state.writer.db.set_progress_handler(progress,1)
     try:operation(state,name)
     except Exception as exc:held.append(exc)
     finally:
      state.writer.db.set_progress_handler(None,0);state.writer.db.set_trace_callback(None)
     row=dict(operation=name,archived=archived,target=target,instruction_budget=instruction_budget,interrupted=interrupted,last_sql=last,
       errors=[dict(type=type(e).__name__,message=str(e),code=getattr(e,'sqlite_errorcode',None)) for e in held])
     try:row['checkpoint']=state.writer.db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchall()
     except Exception as exc:
      row['checkpoint_error']=dict(type=type(exc).__name__,message=str(exc),code=getattr(exc,'sqlite_errorcode',None))
      try:row['busy_statements']=state.writer.db.execute('SELECT sql,busy FROM sqlite_stmt WHERE busy').fetchall()
      except sqlite3.Error:row['statement_inspection_unavailable']=True
     try:state.writer.close()
     except Exception as exc:row['close_error']=type(exc).__name__
     results.append(row)
print('SQLITE_PROBE',json.dumps(results,sort_keys=True))
assert not any('checkpoint_error' in r for r in results),'retained exception blocks SQLite checkpoint'
