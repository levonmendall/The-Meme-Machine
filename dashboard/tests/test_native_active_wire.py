"""Optional cross-repository canonical wire proof on disposable native books.

Host/adoption and fixture identity/risk seams are explicit. No live account,
provider or trading service is used. This does not establish a live PAPER fill.
"""
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from dashboard import active_portfolio as selected
from dashboard.__main__ import make_server
from dashboard.api import Dashboard
from dashboard.model import stamp
from dashboard.snapshots import SnapshotStore
from dashboard.tests.test_simulator import original_snapshot, OWNER, OWNER_AUTH, ORIGINAL_TOKEN, SIMULATOR_TOKEN

APP_SOURCE = os.environ.get('PONS_OBSERVER_TEST_APP_SOURCE')
ADMIN_SOURCE = os.environ.get('PONS_ADMIN_TEST_SOURCE')


@unittest.skipUnless(APP_SOURCE and ADMIN_SOURCE, 'requires frozen native library and admin reporting source')
class NativeActiveWireTests(unittest.TestCase):
    def test_native_entry_partial_settlement_and_restart_match_canonical_financial_apis(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); path = root/'frames.json'
            result = subprocess.run([sys.executable, '-I', '-B',
                str(Path(ADMIN_SOURCE)/'tests/pons_active_wire_fixture.py'),
                APP_SOURCE, ADMIN_SOURCE, str(path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            frames = json.loads(path.read_bytes())['frames']
            identity = frames[0]['portfolio']['observation']['financial_statement']
            source = frames[0]['source']['candidate_commit']; clock = [stamp(frames[0]['captured_at'])]
            # Only this disposable fixture's identity/risk differ from the fixed
            # production experiment. Native exporter and receiver remain real.
            with patch.object(selected, 'EXPERIMENT_EPOCH', identity['epoch_id']), \
                 patch.object(selected, 'EXPERIMENT_INCEPTION', identity['inception_sha256']), \
                 patch.object(selected, 'RISK_SHA256', identity['risk_sha256']):
                archive = SnapshotStore(root/'original-archive.json',
                    epoch='synthetic-original-dashboard', candidate='1'*40, clock=lambda: clock[0])
                archive.accept(original_snapshot(clock[0])); original = archive.path.read_bytes()
                active = selected.ActivePortfolioStore(root/'active.json', archive_path=archive.path,
                    epoch=identity['epoch_id'], candidate=source, inception_sha256=identity['inception_sha256'],
                    clock=lambda: clock[0])
                reader = selected.ActivePortfolioReader(active, clock=lambda: clock[0])
                server = make_server(Dashboard(reader), '127.0.0.1', 0, owner=OWNER, public_reads=False,
                    ingest_token=ORIGINAL_TOKEN, snapshot_store=archive, simulator_ingest_token=SIMULATOR_TOKEN,
                    active_portfolio_store=active, rate_limit_per_minute=600)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def get(route):
                    with urlopen(Request(base+'/api/dashboard/'+route,
                            headers={'Authorization': OWNER_AUTH}), timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        return json.loads(response.read())
                try:
                    for index, frame in enumerate(frames):
                        clock[0] = stamp(frame['captured_at'])
                        request = Request(base+'/api/dashboard/active-portfolio/snapshot', method='POST',
                            data=json.dumps(frame).encode(), headers={'Authorization': 'Bearer '+SIMULATOR_TOKEN,
                            'Content-Type': 'application/json'})
                        with urlopen(request, timeout=3) as response: self.assertEqual(response.status, 202)
                        portfolio = get('portfolio')['data']; positions = get('positions'); trades = get('trades')
                        chart = get('equity?series=portfolio')
                        balances = frame['portfolio']['bundle']['export']['balances']
                        self.assertEqual(portfolio['financial_identity'], chart['financial_identity'])
                        self.assertEqual(portfolio['financial_statement'], frame['portfolio']['observation']['financial_statement'])
                        for key in ('available_cash', 'reserved_cash', 'deployed_capital', 'realized_pnl', 'fees'):
                            self.assertEqual(Decimal(portfolio['metrics'][key]['value']), Decimal(balances[key]))
                        if balances['equity'] is None:
                            self.assertIsNone(portfolio['metrics']['equity']['value'])
                        else:
                            self.assertEqual(Decimal(portfolio['metrics']['equity']['value']), Decimal(balances['equity']))
                        self.assertEqual(positions['total'], (0, 1, 1, 0)[index])
                        self.assertEqual(trades['total'], (0, 0, 0, 1)[index])
                        self.assertEqual(archive.path.read_bytes(), original)
                    reopened = selected.ActivePortfolioStore(active.path, archive_path=archive.path,
                        epoch=identity['epoch_id'], candidate=source, inception_sha256=identity['inception_sha256'],
                        clock=lambda: clock[0])
                    after = selected.ActivePortfolioReader(reopened, clock=lambda: clock[0]).view()['portfolio']
                    self.assertEqual(after['financial_statement'], portfolio['financial_statement'])
                    clock[0] += 61
                    self.assertEqual(get('portfolio')['data']['snapshot_state'], 'STALE')
                    self.assertEqual(archive.path.read_bytes(), original)
                finally:
                    server.shutdown(); server.server_close(); thread.join(3)
