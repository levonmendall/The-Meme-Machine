import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from certification.historical_inventory import inspect_archive


class HistoricalInventoryTests(unittest.TestCase):
    def test_digest_and_projection_scope_preserve_unresolved_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'native.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE positions(id TEXT,body TEXT)')
                db.execute('CREATE TABLE journal(body TEXT)')
                body = json.dumps(dict(status='unresolved', reserved=400,
                    rpc_url='https://secret.invalid/key', tokens=2))
                db.execute('INSERT INTO positions VALUES(?,?)', ('one', body))
                db.executemany('INSERT INTO journal VALUES(?)', [(body,)]*3)
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as z:
                z.write(path, 'historical/pump/native.sqlite')
            data = output.getvalue()
        with self.assertRaisesRegex(ValueError, 'digest_mismatch'):
            inspect_archive(data, 1, '0'*64)
        result = inspect_archive(data, 1, hashlib.sha256(data).hexdigest())
        tables = result['databases'][0]['tables']
        self.assertEqual(tables['positions']['projection_states'], {'unresolved': 1})
        self.assertEqual(tables['positions']['projections'][0]['reserved'], 400)
        self.assertEqual(tables['journal'], {'rows': 3})
        self.assertNotIn('secret.invalid', json.dumps(result))
        self.assertFalse(result['accounting_recovery_certified'])
