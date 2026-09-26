import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from certification import single_campaign_control as control
from certification import prospective_program as program


SHA = 'a' * 40
REF = 'cert/single-market-evidence-reconstruction-20260924'


class API:
    def __init__(self):
        self.calls = []
        self.runs = {status: [] for status in control.ACTIVE_STATUSES}
        self.jobs = {}
        self.detail = {}
        self.post_error = None
        self.ref_sha = SHA

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == 'POST':
            if self.post_error:
                raise self.post_error
            return None
        if path.startswith('git/ref/'):
            return {'object': {'sha': self.ref_sha}}
        query = parse_qs(urlsplit(path).query)
        if path.startswith('actions/runs?'):
            rows = self.runs[query['status'][0]]
            page = int(query['page'][0])
            return {'workflow_runs': rows[(page-1)*100:page*100], 'total_count': len(rows)}
        if '/jobs?' in path:
            run = int(path.split('/')[2]); rows = self.jobs.get(run, [])
            page = int(query['page'][0])
            return {'jobs': rows[(page-1)*100:page*100], 'total_count': len(rows)}
        run = int(path.split('/')[2])
        return self.detail.get(run, dict(status='completed', conclusion='success', head_sha=SHA))


def market(identifier, status='queued', path=control.MARKET_WORKFLOW):
    return dict(id=identifier, status=status, path=path)


class SingleCampaignTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {'SINGLE_AUTHORIZATION_ID': 'unit-single-campaign-v1'}, clear=False)
        self.env_patch.start(); self.addCleanup(self.env_patch.stop)
        self.config = control.configuration()
        self.identity = dict(integration_sha=SHA, implementation_hash='impl', source_manifest_hash='sources',
                             source_diff_hashes={'pump': 'diff'}, protocol_sha256='policy')
        self.memory = {'state': None, 'version': 0, 'fail_write': False}
        memory = self.memory
        class Store:
            def __init__(self, *args):
                self.version = None
            def read(self):
                self.version = memory['version']
                return copy.deepcopy(memory['state'])
            def write(self, state):
                if memory['fail_write'] or self.version != memory['version']:
                    raise ValueError('state_compare_and_swap_failed')
                memory['state'] = copy.deepcopy(state)
                memory['version'] += 1
                self.version = memory['version']
        self.store_patch = patch.object(control, 'StateStore', Store)
        self.store_patch.start(); self.addCleanup(self.store_patch.stop)
        self.cert_patch = patch.object(program, 'certificate', return_value=dict(self.identity, passed=True))
        self.cert_patch.start(); self.addCleanup(self.cert_patch.stop)
        self.api = API()
        self.api.detail[5] = dict(path='.github/workflows/single-campaign-launch.yml',
            head_branch=control.LAUNCH_BRANCH, event='push',
            run_attempt=1, head_sha='b'*40, head_commit={'message': '[single-market-launch]'})

    def dispatch(self, attempt='1'):
        return control.dispatch_once(self.api, self.config, self.identity, 99, REF, 5, attempt)

    def market_posts(self):
        return [call for call in self.api.calls if call[0] == 'POST' and call[1].endswith('/dispatches')]

    def prepare_claim(self, run=22):
        self.dispatch()
        self.api.detail[run] = dict(head_sha=SHA, head_branch=REF, run_attempt=1,
            event='workflow_dispatch', path=control.MARKET_WORKFLOW)
        return self.memory['state']['dispatch_id']

    def claimed(self):
        nonce = self.prepare_claim()
        return control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], nonce)

    def native_result(self, phase='smoke', open_lane=None):
        return dict(integration_sha=SHA, phase=phase, run_id='native', status='FINISHED',
                    lanes={lane: dict(open_positions=int(lane == open_lane), accounting_reconciled=True,
                                      durable_handoff=(lane == open_lane)) for lane in control.LANES})

    def test_authorization_is_external_to_certified_runtime_policy(self):
        self.assertEqual(self.config['authorization_id'], 'unit-single-campaign-v1')
        first = control.runtime_policy(self.config)
        with patch.dict(os.environ, {'SINGLE_AUTHORIZATION_ID': 'unit-single-campaign-v2'}, clear=False):
            second_config = control.configuration()
        self.assertEqual(second_config['authorization_id'], 'unit-single-campaign-v2')
        self.assertEqual(first, control.runtime_policy(second_config))
        self.assertNotIn('authorization_id', first)
        self.assertNotIn('prior_run_observation', first)
        self.assertNotIn('prior_launch_attempt', first)

    def test_single_post_and_durable_duplicate_rejection(self):
        self.dispatch()
        self.assertFalse(self.memory['state']['successor_allowed'])
        self.assertFalse(self.memory['state']['continuation_allowed'])
        self.assertTrue(self.memory['state']['position_continuation_authorized'])
        with self.assertRaisesRegex(ValueError, 'already_consumed'):
            self.dispatch()
        self.assertEqual(len(self.market_posts()), 1)
        self.assertEqual(self.market_posts()[0][2]['inputs']['program'], 'false')

    def test_ambiguous_http_response_is_consumed_and_never_retried(self):
        self.api.post_error = TimeoutError('response lost after server may have accepted')
        with self.assertRaises(TimeoutError):
            self.dispatch()
        self.assertEqual(self.memory['state']['phase'], 'DISPATCH_COMMITTED')
        with self.assertRaisesRegex(ValueError, 'already_consumed'):
            self.dispatch()
        self.assertEqual(len(self.market_posts()), 1)

    def test_ambiguous_durable_write_never_reaches_dispatch(self):
        self.memory['fail_write'] = True
        with self.assertRaisesRegex(ValueError, 'compare_and_swap'):
            self.dispatch()
        self.assertEqual(self.market_posts(), [])

    def test_launcher_rerun_rejected_before_api_or_state(self):
        with self.assertRaisesRegex(ValueError, 'rerun_prohibited'):
            self.dispatch('2')
        self.assertEqual(self.api.calls, [])
        self.assertIsNone(self.memory['state'])

    def test_failed_or_running_certificate_never_consumes_authority(self):
        for status, conclusion in [('in_progress', None), ('completed', 'failure')]:
            self.api.detail[99] = dict(status=status, conclusion=conclusion)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'not_terminal_success'):
                self.dispatch()
        self.assertIsNone(self.memory['state']); self.assertEqual(self.market_posts(), [])

    def test_certificate_or_ref_drift_rejected(self):
        with patch.object(program, 'certificate', return_value=dict(self.identity, implementation_hash='other')):
            with self.assertRaisesRegex(ValueError, 'certificate_identity'):
                self.dispatch()
        self.api.ref_sha = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'runtime_ref_drift'):
            self.dispatch()
        self.assertEqual(self.market_posts(), [])

    def test_dirty_or_untracked_configuration_cannot_claim_certified_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {'certification/config.json': b'{"frozen":true}',
                     '.github/workflows/market.yml': b'name: frozen\n'}
            lines = []
            for name, data in files.items():
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                lines.append('100644 blob ' + oid + '\t' + name)
            def git(*args):
                return SHA if args[0] == 'rev-parse' else '\n'.join(lines)
            with patch.object(control, 'ROOT', root), patch.object(control, 'git', side_effect=git):
                self.assertEqual(len(control.checkout_files(SHA)), 64)
                (root/'certification/config.json').write_text('{"frozen":false}')
                with self.assertRaisesRegex(ValueError, 'checkout_file'):
                    control.checkout_files(SHA)
                (root/'certification/config.json').write_bytes(files['certification/config.json'])
                (root/'certification/extra.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'uncommitted_runtime_configuration'):
                    control.checkout_files(SHA)

    def test_every_nonterminal_market_status_blocks_even_without_jobs(self):
        for status in control.ACTIVE_STATUSES:
            api = API(); api.runs[status] = [market(40, status)]
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'other_market_workflow'):
                control.contention(api, 5)

    def test_offline_job_and_certificate_are_not_market_contention(self):
        self.api.runs['in_progress'] = [market(40, 'in_progress', '.github/workflows/ci.yml'),
            market(41, 'in_progress', '.github/workflows/evidence-reconstruction-certification.yml')]
        self.api.jobs[40] = [dict(id=400, name='test', status='in_progress')]
        self.assertTrue(control.contention(self.api, 5)['passed'])

    def test_reviewed_offline_wrappers_are_not_market_contention(self):
        for name in (
            'v10-provider-pressure-nonmarket-certification.yml',
            'ramses-v4-offline-certification.yml',
            'ramses-v4-launchable-nonmarket-certification.yml',
            'v12-active-strategy-certification.yml',
        ):
            api = API()
            api.runs['in_progress'] = [market(42, 'in_progress', '.github/workflows/' + name)]
            api.jobs[42] = [dict(id=420, name='certify / offline-prerequisites', status='in_progress')]
            with self.subTest(name=name):
                self.assertTrue(control.contention(api, 5)['passed'])

    def test_other_launcher_and_historical_cohort_review_block_dispatch(self):
        for name in ('single-campaign-launch.yml', 'prospective-cohort-review.yml'):
            self.api.runs['requested'] = [market(70, 'requested', '.github/workflows/' + name)]
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'other_market_workflow'):
                control.contention(self.api, 5)

    def test_claim_allows_only_its_consumed_launcher_upload_tail(self):
        nonce = self.prepare_claim()
        self.api.runs['in_progress'] = [market(5, 'in_progress', '.github/workflows/single-campaign-launch.yml')]
        claimed = control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], nonce)
        self.assertEqual(claimed['workflow_run_id'], 22)
        self.api.runs['in_progress'].append(market(6, 'in_progress', '.github/workflows/single-campaign-launch.yml'))
        with self.assertRaisesRegex(ValueError, 'other_market_workflow'):
            control.owned_contention(self.api, claimed, 22)

    def test_second_run_page_is_examined(self):
        rows = [market(n, path='.github/workflows/non-market-certification.yml') for n in range(100, 200)]
        self.api.runs['queued'] = rows + [market(500)]
        with self.assertRaisesRegex(ValueError, 'other_market_workflow'):
            control.contention(self.api, 5)
        self.assertTrue(any('status=queued&per_page=100&page=2' in p for _, p, _ in self.api.calls))

    def test_second_job_page_and_unknown_queued_workflow_fail_closed(self):
        self.api.runs['queued'] = [market(80, path='.github/workflows/unknown.yml')]
        self.api.jobs[80] = [dict(id=n, name='test', status='queued') for n in range(100)] + [
            dict(id=100, name='new-market-worker', status='queued')]
        with self.assertRaisesRegex(ValueError, 'other_market_workflow'):
            control.contention(self.api, 5)
        self.api.jobs[80] = []
        with self.assertRaisesRegex(ValueError, 'other_market_workflow'):
            control.contention(self.api, 5)

    def test_filtered_total_count_race_exhausts_to_empty_page(self):
        class Moving:
            def __init__(self): self.calls=0
            def request(self, *args):
                self.calls+=1
                if self.calls==1:
                    return dict(workflow_runs=[market(1, path='.github/workflows/non-market-certification.yml')], total_count=2)
                return dict(workflow_runs=[], total_count=0)
        api=Moving()
        rows=control.all_pages(api, 'actions/runs?status=queued', 'workflow_runs')
        self.assertEqual([row['id'] for row in rows],[1])
        self.assertEqual(api.calls,2)

    def test_capped_active_inventory_never_passes(self):
        self.api.runs['queued'] = [market(n, path='.github/workflows/non-market-certification.yml') for n in range(1000)]
        with self.assertRaisesRegex(ValueError, 'search_cap'):
            control.contention(self.api, 5)

    def test_new_market_run_between_intent_and_post_burns_authority_without_dispatch(self):
        original = control.contention; scans = []
        def checked(api, exclude):
            scans.append(True)
            if len(scans) == 2:
                api.runs['waiting'] = [market(50, 'waiting')]
            return original(api, exclude)
        with patch.object(control, 'contention', side_effect=checked):
            with self.assertRaisesRegex(ValueError, 'other_market_workflow'):
                self.dispatch()
        self.assertIsNotNone(self.memory['state']); self.assertEqual(self.market_posts(), [])
        with self.assertRaisesRegex(ValueError, 'already_consumed'):
            self.dispatch()

    def test_claim_bound_to_one_run_and_no_rerun(self):
        nonce = self.prepare_claim()
        claimed = control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], nonce)
        self.assertEqual(claimed['workflow_run_id'], 22)
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], nonce)
        before = len(self.api.calls)
        with self.assertRaisesRegex(ValueError, 'rerun_prohibited'):
            control.claim(self.api, self.config, self.identity, 22, '2', self.config['authorization_id'], nonce)
        self.assertEqual(before, len(self.api.calls))

    def test_claim_rejects_wrong_sha_nonce_workflow_or_run_attempt(self):
        nonce = self.prepare_claim()
        for key, wrong in [('head_sha', 'b'*40), ('path', '.github/workflows/position-continuation.yml'),
                           ('run_attempt', 2)]:
            original = copy.deepcopy(self.api.detail[22]); self.api.detail[22][key] = wrong
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'run_identity'):
                control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], nonce)
            self.api.detail[22] = original
        with self.assertRaisesRegex(ValueError, 'consumed_authority_required'):
            control.claim(self.api, self.config, self.identity, 22, '1', self.config['authorization_id'], 'other')

    def test_only_smoke_then_hourly_in_same_claim_no_phase_retry(self):
        state = self.claimed()
        with self.assertRaisesRegex(ValueError, 'smoke_not_complete'):
            control.begin_phase(state, 'hourly')
        state = control.begin_phase(state, 'smoke')
        with self.assertRaisesRegex(ValueError, 'phase_repeated'):
            control.begin_phase(state, 'smoke')
        state = control.end_phase(state, 'smoke', self.native_result(), 'success')
        state = control.begin_phase(state, 'hourly')
        state = control.end_phase(state, 'hourly', self.native_result('hourly'), 'success')
        self.assertEqual(state['phase'], 'HALTED')
        with self.assertRaisesRegex(ValueError, 'phase_not_authorized'):
            control.begin_phase(state, 'smoke')

    def test_unresolved_native_position_preserved_without_continuation_or_fake_settlement(self):
        state = control.begin_phase(self.claimed(), 'smoke')
        state = control.end_phase(state, 'smoke', self.native_result(open_lane='ramses'), 'success')
        self.assertEqual(state['phase'], 'HALTED_UNRESOLVED')
        self.assertEqual(state['phase_records']['smoke']['native_positions']['ramses']['open_positions'], 1)
        self.assertFalse(state['continuation_allowed'])
        with self.assertRaisesRegex(ValueError, 'phase_not_authorized'):
            control.begin_phase(state, 'hourly')

    def test_hourly_durable_position_allows_position_only_continuation(self):
        state=control.begin_phase(self.claimed(),'smoke')
        state=control.end_phase(state,'smoke',self.native_result(),'success')
        state=control.begin_phase(state,'hourly')
        state=control.end_phase(state,'hourly',self.native_result('hourly',open_lane='meteora'),'success')
        self.assertEqual(state['phase'],'POSITION_CONTINUATION')
        self.assertTrue(state['continuation_allowed'])
        self.assertFalse(state['successor_allowed'])
        self.assertIn('no new discovery',state['next_action'])

    def test_missing_result_and_cancelled_or_failed_phase_cannot_resume(self):
        for result, job in [(None, 'cancelled'), (self.native_result(), 'failure')]:
            state = dict(phase='CLAIMED', phase_records={}, identity=self.identity, history=[])
            state = control.begin_phase(state, 'smoke')
            state = control.end_phase(state, 'smoke', result, job)
            self.assertTrue(state['phase'].startswith('HALTED'))
            with self.assertRaisesRegex(ValueError, 'phase_not_authorized'):
                control.begin_phase(state, 'hourly')

    def test_legacy_program_and_continuation_authority_are_disabled(self):
        with self.assertRaisesRegex(ValueError, 'prohibits_successor_dispatch'):
            program.dispatch(self.api, {}, SHA, 'policy')
        with self.assertRaisesRegex(ValueError, 'prohibits_continuation'):
            control.prohibit_if_enabled('continuation')
        self.assertEqual(self.api.calls, [])

    def test_smoke_register_and_complete_block_before_api_or_state_mutation(self):
        from certification import smoke_continuation
        for command in ('register', 'complete'):
            argv = ['smoke_continuation', command, '--run-id', '22', '--output', 'unused.json']
            with self.subTest(command=command), patch('sys.argv', argv), \
                 patch.object(smoke_continuation, 'GitHub') as github, \
                 patch.object(smoke_continuation, 'commit_transition') as transition:
                with self.assertRaisesRegex(ValueError, 'prohibits_smoke_continuation_' + command):
                    smoke_continuation.main()
                github.assert_not_called(); transition.assert_not_called()

    def test_legacy_mutating_commands_block_before_api_or_state_mutation(self):
        for command in ('start', 'claim', 'advance', 'retire'):
            with self.subTest(command=command), patch('sys.argv', ['program', command]), \
                 patch.object(program, 'GitHub') as github, \
                 patch.object(program, 'commit_transition') as transition:
                with self.assertRaisesRegex(ValueError, 'prohibits_legacy_program_' + command):
                    program.main()
                github.assert_not_called(); transition.assert_not_called()

    def test_workflow_entry_points_preserve_one_shot_boundary(self):
        root = control.ROOT / '.github/workflows'
        four = (root/'four-lane-certification.yml').read_text()
        self.assertNotIn('\n  push:', four.split('permissions:', 1)[0])
        self.assertIn('single_campaign_control claim', four)
        self.assertIn('Start position-only continuation for durable open long-horizon positions', four)
        launcher = (root/'single-campaign-launch.yml').read_text()
        self.assertIn('SINGLE_AUTHORIZATION_ID: ${{ steps.request.outputs.authorization_id }}', launcher)
        continuation = (root/'position-continuation.yml').read_text()
        self.assertIn('authorization_id:', continuation)
        self.assertIn('-f authorization_id="${{ inputs.authorization_id }}"', continuation)
        self.assertLess(continuation.index('single_campaign_control continuation-claim'),
                        continuation.index('Restore exact prior position artifact'))
        self.assertIn('single-campaign-continuation-state.json',continuation)
        wrapper = (root/'evidence-reconstruction-certification.yml').read_text()
        self.assertNotIn('dispatches', wrapper)
        self.assertNotIn('workflow_run:', wrapper)


if __name__ == '__main__':
    unittest.main()
