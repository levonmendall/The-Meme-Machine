"""Budget namespace filtering preserves selected state and accounting behavior.

All ledgers, responses and provider identities are disposable offline fixtures.
Cursor counts describe this query's rows, never measured AWS throughput. Foreign
invalid UTF-8 is isolated explicitly; selected malformed state still refuses.
"""
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget,CeilingReached,DeliveredResponse,MAX_FRAME,USAGE_COUNTERS
from tests import test_bounded_provider_preflight as bounded_fixture
from tests import test_continuous_paper as continuous_fixture
from tests import test_position_continuation as continuation_fixture


PHASES=('bootstrap','continuation','recovery')
ENDPOINT='https://solana-mainnet.g.alchemy.com/v2/offline-budget-namespace'


def python_reference(budget,db):
    # The exact predecessor comprehension remains the parity oracle.
    return {key[len(budget.prefix):]:value for key,value in db.execute('SELECT key,value FROM run')
        if (key.startswith(budget.prefix) if budget.prefix else '.' not in key)}


class PythonReferenceBudget(Budget):
    read=python_reference


class CountingCursor(sqlite3.Cursor):
    def __next__(self):
        self.connection.next_calls+=1
        row=super().__next__();self.connection.yielded_rows+=1
        return row


class CountingConnection(sqlite3.Connection):
    def execute(self,sql,parameters=(),/):
        return self.cursor(factory=CountingCursor).execute(sql,parameters)

    def reset_counts(self):self.yielded_rows=0;self.next_calls=0


class ProviderBudgetNamespaceReadTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def table(self):
        db=sqlite3.connect(':memory:',isolation_level=None,factory=CountingConnection)
        self.addCleanup(db.close)
        db.reset_counts()
        db.execute('CREATE TABLE run(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        return db

    @staticmethod
    def reader(phase):
        budget=object.__new__(Budget)
        budget.phase=phase;budget.prefix='' if phase=='bootstrap' else phase+'.'
        return budget

    def test_actual_392_row_shape_returns_only_35_bootstrap_rows_and_exact_phase_results(self):
        db=self.table()
        rows=[('base_'+str(n),'base-value-'+str(n)) for n in range(35)]
        rows += [('continuation.phase_'+str(n),'continuation-value-'+str(n)) for n in range(178)]
        rows += [('recovery.phase_'+str(n),'recovery-value-'+str(n)) for n in range(179)]
        db.executemany('INSERT INTO run VALUES(?,?)',rows)
        self.assertEqual(len(rows),392)
        for phase,selected in zip(PHASES,(35,178,179)):
            budget=self.reader(phase)
            db.reset_counts();expected=python_reference(budget,db)
            self.assertEqual((db.yielded_rows,db.next_calls),(392,393))
            db.reset_counts();actual=budget.read(db)
            self.assertEqual(actual,expected)
            self.assertEqual((db.yielded_rows,db.next_calls),(selected,selected+1))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM run').fetchone()[0],392)

    def test_unknown_valid_keys_case_prefix_lookalikes_unicode_and_nul_match_python(self):
        db=self.table()
        keys=('', 'new_unknown_counter','continuation','recovery','UpperCase','space key',
            'unicode。not-ascii-dot','κλειδί','nul\x00before','nul\x00.after',
            'continuation.','continuation.reason','continuation.nested.key','continuation.κλειδί',
            'continuation.%_[]*','continuation.\x00inside.more','Continuation.reason',
            'CONTINUATION.reason','continuationX.reason','continuation_.reason',
            'continuation%.reason','recovery.','recovery.reason','recovery.\x00more',
            'Recovery.reason','recoveryX.reason','other.continuation.reason')
        db.executemany('INSERT INTO run VALUES(?,?)',[(key,'value-'+str(index)) for index,key in enumerate(keys)])
        # Values are preserved too; a BLOB value under a valid text key is not
        # silently decoded or converted by the namespace predicate.
        db.execute('INSERT INTO run VALUES(?,?)',('unknown_blob_value',sqlite3.Binary(b'\x00\xff')))
        for phase in PHASES:
            with self.subTest(phase=phase):
                budget=self.reader(phase)
                self.assertEqual(budget.read(db),python_reference(budget,db))
        self.assertEqual(self.reader('bootstrap').read(db)['unknown_blob_value'],b'\x00\xff')

    def test_null_and_blob_keys_keep_exact_predecessor_fail_closed_exception_classes(self):
        for phase in PHASES:
            for malformed in (None,sqlite3.Binary(b'continuation.bad-key')):
                with self.subTest(phase=phase,key=malformed):
                    db=self.table();db.execute('INSERT INTO run VALUES(?,?)',(malformed,'retained'))
                    budget=self.reader(phase)
                    with self.assertRaises((TypeError,AttributeError)) as original:python_reference(budget,db)
                    with self.assertRaises(type(original.exception)):budget.read(db)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM run').fetchone()[0],1)

    def test_selected_invalid_utf8_still_refuses_decoding_for_each_phase(self):
        for phase in PHASES:
            for malformed in ('key','value'):
                with self.subTest(phase=phase,field=malformed):
                    db=self.table();budget=self.reader(phase)
                    if malformed=='key':
                        db.execute("INSERT INTO run VALUES(?||CAST(X'80' AS TEXT),'retained')",(budget.prefix,))
                    else:
                        db.execute("INSERT INTO run VALUES(?,CAST(X'80' AS TEXT))",(budget.prefix+'selected',))
                    with self.assertRaises(sqlite3.OperationalError):python_reference(budget,db)
                    with self.assertRaises(sqlite3.OperationalError):budget.read(db)

    def test_foreign_invalid_utf8_isolated_explicitly_instead_of_claimed_full_table_parity(self):
        for malformed in ('key','value'):
            with self.subTest(field=malformed):
                db=self.table();db.execute("INSERT INTO run VALUES('reason','')")
                if malformed=='key':db.execute("INSERT INTO run VALUES('continuation.'||CAST(X'80' AS TEXT),'foreign')")
                else:db.execute("INSERT INTO run VALUES('continuation.foreign',CAST(X'80' AS TEXT))")
                bootstrap=self.reader('bootstrap')
                with self.assertRaises(sqlite3.OperationalError):python_reference(bootstrap,db)
                self.assertEqual(bootstrap.read(db),{'reason':''})
                # Selecting that namespace still exposes the real malformed
                # ledger; this is not a repair, normalization or deletion.
                with self.assertRaises(sqlite3.OperationalError):self.reader('continuation').read(db)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM run').fetchone()[0],2)

    def test_independent_commits_are_visible_without_cached_namespace_state(self):
        path=self.root/'phase-usage.sqlite'
        Budget.create(path,continuation=continuation_fixture.envelope())
        budgets={phase:Budget(path,phase=phase) for phase in PHASES}
        with closing(sqlite3.connect(path,isolation_level=None)) as writer, \
                closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None)) as reader:
            for phase,budget in budgets.items():
                key=budget.prefix+'unknown_fresh_fact'
                writer.execute('INSERT INTO run VALUES(?,?)',(key,'first'))
                self.assertEqual(budget.read(reader)['unknown_fresh_fact'],'first')
                writer.execute('BEGIN IMMEDIATE')
                writer.execute('UPDATE run SET value=? WHERE key=?',('second',key))
                writer.execute('COMMIT')
                actual=budget.read(reader)
                self.assertEqual(actual['unknown_fresh_fact'],'second')
                self.assertEqual(actual,python_reference(budget,reader))

    @staticmethod
    def state_without_creation_clock(budget):
        return {key:value for key,value in budget.snapshot().items() if key not in ('started','started_wall')}

    def exercise_continuous(self,kind,path,profile):
        budget=kind.create(path,continuous=profile)
        with closing(budget.db()) as db:
            db.executemany('INSERT INTO run VALUES(?,?)',
                [('continuation.foreign_'+str(n),'retained-'+str(n)) for n in range(357)])
            foreign_before=db.execute("SELECT key,value FROM run WHERE key LIKE 'continuation.foreign_%' ORDER BY key").fetchall()
        payload=b'offline-authenticated-response-shape'
        receipt=budget.reserve_http(ENDPOINT,[dict(method='getSlot')])
        self.assertEqual(budget.snapshot()['http_reserved'],str(MAX_FRAME))
        with DeliveredResponse(io.BytesIO(payload),receipt) as response:
            self.assertEqual(response.read(5)+response.read(),payload)
        receipt.close()
        state=budget.snapshot()
        self.assertEqual((state['http_attempts'],state['rpc_elements'],state['rpc_cu']),('1','1','20'))
        self.assertEqual((state['http_bytes'],state['http_reserved'],state['http_uncertain_bytes']),
            (str(len(payload)),'0','0'))
        capacity=profile['limits']['http_inflight_bytes']//MAX_FRAME
        held=[budget.reserve_http(ENDPOINT,[dict(method='getSlot')]) for _ in range(capacity)]
        before=budget.snapshot()
        with self.assertRaisesRegex(CeilingReached,'http_inflight_limit'):budget.reserve_http(ENDPOINT,[dict(method='getSlot')])
        after=budget.snapshot()
        for key in ('http_attempts','rpc_elements','rpc_cu','http_reserved','http_bytes'):
            self.assertEqual(after[key],before[key])
        for receipt in held:receipt.close();receipt.close()
        after=budget.snapshot()
        self.assertEqual(after['http_reserved'],'0')
        self.assertEqual(int(after['http_uncertain_bytes']),capacity*MAX_FRAME)
        report=budget.usage()
        self.assertEqual(report['periods']['hourly']['http_bytes'],len(payload))
        self.assertEqual(report['periods']['hourly']['http_attempts'],capacity+1)
        with closing(budget.db()) as db:
            sums=db.execute('SELECT '+','.join('SUM('+key+')' for key in USAGE_COUNTERS)+' FROM usage_hours').fetchone()
            self.assertEqual(dict(zip(USAGE_COUNTERS,sums)),{key:int(after[key]) for key in USAGE_COUNTERS})
            receipts=db.execute('SELECT remaining,closed,owner FROM http_receipts ORDER BY remaining,closed,owner').fetchall()
            self.assertTrue(all(row[0]==0 and row[1]==1 for row in receipts))
            self.assertEqual(db.execute("SELECT key,value FROM run WHERE key LIKE 'continuation.foreign_%' ORDER BY key").fetchall(),foreign_before)
        self.assertEqual(kind(path).snapshot(),after)
        return self.state_without_creation_clock(budget),report,receipts

    def test_real_continuous_http_reservations_delivery_close_hourly_usage_match_old_reader(self):
        profile=json.loads(continuous_fixture.PROFILE.read_text())
        with patch('time.time',return_value=1791400000.):
            expected=self.exercise_continuous(PythonReferenceBudget,self.root/'old-reader.sqlite',profile)
            actual=self.exercise_continuous(Budget,self.root/'namespace-reader.sqlite',profile)
        self.assertEqual(actual,expected)

    def test_real_bounded_failed_admission_preserves_consumption_and_foreign_state(self):
        outputs=[]
        for kind,name in ((PythonReferenceBudget,'old'),(Budget,'new')):
            budget=kind.create(self.root/(name+'-bounded.sqlite'),limits=bounded_fixture.LIMITS)
            with closing(budget.db()) as db:
                db.execute("INSERT INTO run VALUES('recovery.retained_fact','unchanged')")
                db.execute("UPDATE run SET value='150000' WHERE key='rpc_cu'")
            before=budget.snapshot()
            with self.assertRaisesRegex(CeilingReached,'rpc_cu_limit'):budget.reserve_http(ENDPOINT,[dict(method='getSlot')])
            after=budget.snapshot()
            for key in before.keys()-{'reason'}:self.assertEqual(after[key],before[key])
            with closing(budget.db()) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM http_receipts').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT value FROM run WHERE key='recovery.retained_fact'").fetchone()[0],'unchanged')
            outputs.append(self.state_without_creation_clock(budget))
        self.assertEqual(outputs[0],outputs[1])
