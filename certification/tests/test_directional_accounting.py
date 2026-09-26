import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from certification.survivor_paper_book import PaperBook
from certification.survivor_history import History
from certification.sleeve_reservations import SleeveReservations
from certification.directional_accounting import terminal,combine,execution_cost

class DirectionalAccounting(unittest.TestCase):
 def test_exact_partial_cash_basis_and_only_committed_gas(self):
  with tempfile.TemporaryDirectory() as td:
   book=PaperBook(Path(td)/'paper',run_id='r',lane='survivor',policy_hash='b',initial=1000)
   book.reserve('r:p',100,1,{})
   book.transition('r:p','filled',2,amount=100,tokens=400,evidence={'execution':{'gas':3,'roundtrip_gas':8}})
   book.transition('r:p','partial_harvest',3,amount=32,tokens=100,evidence={'execution':{'gas':2}})
   self.assertEqual(execution_cost(book),5)
   status=dict(accounting=book.reconcile(),sleeve={'capital':1000,'reconciled':True,'realized':0,'available':900,'reserved':100},policies={'current':'a','survivor':'b'},native_execution_cost=5)
   c=dict(genesis=1000,cash=800,remaining_cost_basis=200,booked_realized=0,realized=0,unsettled=1,positions=1,available=800,reserved=200,
      capital_at_risk_unit_nanoseconds=0,native_execution_cost=4,native_observation_complete=True,cash_basis_conservation=True)
   result=combine('pons',c,status)
   self.assertEqual((result['cash'],result['remaining_cost_basis'],result['booked_realized'],result['native_execution_cost']),(732,275,7,9))
   self.assertEqual(result['genesis'],1000);book.close()

 def test_terminal_proves_both_namespaces_and_refuses_orphan_capital(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);folder=root/'pump-survivor';folder.mkdir()
   current=PaperBook(root/'pump-acceleration-natural-prospective.accounting.sqlite3',run_id='r',lane='current',policy_hash='a',initial=1000)
   book=PaperBook(folder/'paper.sqlite',run_id='r',lane='survivor',policy_hash='b',initial=1000)
   history=History(folder/'history.sqlite',policy='b')
   sleeve=SleeveReservations(root/'directional-sleeve.sqlite',lane='pump',capital=1000,policies={'current':'a','survivor':'b'},cohort='c')
   sleeve.reserve('r:current',strategy='current',amount=400,at=1)
   current.reserve('r:current',400,1,{})
   sleeve.reserve('r:survivor',strategy='survivor',amount=100,at=1)
   book.reserve('r:survivor',100,1,{})
   book.transition('r:survivor','filled',2,amount=100,tokens=400,evidence={})
   row=history.graduate('mint',{'at':1});row['position']='r:survivor';history.save(row)
   prior=dict(verified=True,accounting=current.reconcile(),open_positions=1)
   with patch('certification.directional_sleeve.policies',return_value={'current':'a','survivor':'b'}):
    result=terminal('pump',root,prior)
    self.assertEqual(result['open_positions'],2);self.assertEqual(result['accounting']['initial'],1000)
    self.assertEqual(result['accounting']['cash'],500);self.assertFalse(result['durable_handoff'])
    sleeve.reserve('r:orphan',strategy='current',amount=1,at=1)
    with self.assertRaisesRegex(ValueError,'unowned_capital'):terminal('pump',root,prior)
   history.close();book.close();current.close();sleeve.close()

 def test_simultaneous_reservations_have_one_durable_order_after_restart(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'sleeve';kwargs=dict(lane='pump',capital=100,policies={'current':'a','survivor':'b'},cohort='c')
   s=SleeveReservations(path,**kwargs);s.close()
   barrier=threading.Barrier(2);outcomes={}
   def worker(strategy):
    book=SleeveReservations(path,**kwargs);barrier.wait()
    try:book.reserve(strategy,strategy=strategy,amount=100,at=1);outcomes[strategy]='reserved'
    except ValueError as exc:outcomes[strategy]=str(exc)
    finally:book.close()
   threads=[threading.Thread(target=worker,args=(key,)) for key in kwargs['policies']]
   for t in threads:t.start()
   for t in threads:t.join()
   self.assertEqual(sorted(outcomes.values()),['reserved','sleeve_capital_exhausted'])
   s=SleeveReservations(path,**kwargs);winner=next(k for k,v in outcomes.items() if v=='reserved')
   self.assertEqual(s.get(winner)['held'],100);self.assertEqual(s.reconcile()['available'],0)
   first=json.loads(s.db.execute('SELECT body FROM sleeve_journal ORDER BY seq LIMIT 1').fetchone()[0])
   self.assertEqual(first['row']['id'],winner);s.close()
