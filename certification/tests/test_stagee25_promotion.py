"""Deterministic promotion tests: fake API writes never reach a real repository."""
from __future__ import annotations

import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from certification import promote_phase_e as promotion
from certification import dispatch_phase_e as dispatch
from certification.tests.test_dispatch_phase_e import SHA, WRONG, PLAN, accepted, build, run

OLD = 'd' * 40
ACTOR = 77


def evidence():
    return dict(cohort=accepted(), build=build(), plan_sha256=PLAN, artifacts={
        'cohort': dict(id=51, name='fixed-cohort', digest='sha256:' + '1' * 64, workflow_run_id=10),
        'build': dict(id=52, name=f'non-market-certification-{SHA}-1',
                      digest='sha256:' + '2' * 64, workflow_run_id=20)})


class FakeAPI:
    """Implements only the reviewed endpoints; unknown operations fail tests."""
    def __init__(self):
        self.calls = []
        self.canonical = OLD
        self.claim = None
        self.intent = None
        self.run = None
        self.actor = dict(id=ACTOR, head_sha=SHA, path=promotion.WORKFLOW,
                          event='workflow_dispatch', run_attempt=1, status='in_progress')
        self.registered = 'active'
        self.wrong_workflow = False
        self.ref_failure = False

    def request(self, method, path, data=None):
        self.calls.append((method, path, deepcopy(data)))
        if method == 'GET' and path == f'actions/runs/{ACTOR}':
            return deepcopy(self.actor)
        if method == 'GET' and path == 'actions/runs/99':
            return deepcopy(self.run)
        if method == 'GET' and path == 'actions/workflows/' + dispatch.WORKFLOW:
            return dict(path='.github/workflows/' + dispatch.WORKFLOW, state=self.registered)
        if method == 'GET' and path.startswith('contents/.github/workflows/'):
            filename = path.split('contents/', 1)[1].split('?ref=', 1)[0]
            raw = b'changed' if self.wrong_workflow else (promotion.ROOT / filename).read_bytes()
            return dict(encoding='base64', content=base64.b64encode(raw).decode())
        if method == 'GET' and path == 'git/ref/heads/' + dispatch.BRANCH:
            return dict(object=dict(sha=self.canonical))
        if method == 'GET' and path == 'git/ref/' + promotion.intent_ref(SHA):
            if self.claim is None:
                raise HTTPError('https://api.github.com/ref', 404, 'not found', {}, None)
            return dict(object=dict(sha=self.claim))
        if method == 'GET' and path.startswith('contents/' + promotion.INTENT_FILE):
            return dict(encoding='base64', content=base64.b64encode(json.dumps(self.intent).encode()).decode())
        if method == 'GET' and path.startswith('actions/workflows/' + dispatch.WORKFLOW + '/runs?'):
            return dict(total_count=bool(self.run), workflow_runs=[deepcopy(self.run)] if self.run else [])
        if method == 'POST' and path == 'git/trees':
            self.intent = json.loads(data['tree'][0]['content'])
            return dict(sha='f' * 40)
        if method == 'POST' and path == 'git/commits':
            return dict(sha='e' * 40)
        if method == 'POST' and path == 'git/refs':
            if self.ref_failure:
                raise TimeoutError('lost creation response')
            if self.claim is not None:
                raise HTTPError('https://api.github.com/ref', 422, 'already exists', {}, None)
            self.claim = data['sha']
            return dict(ref=data['ref'], object=dict(sha=data['sha']))
        if method == 'POST' and path == 'actions/workflows/' + dispatch.WORKFLOW + '/dispatches':
            self.run = run()
            return dict(workflow_run_id=99)
        if method == 'GET' and path == 'actions/runs/99/artifacts?per_page=100&page=1':
            return dict(total_count=0, artifacts=[])
        raise AssertionError((method, path, data))

    def push(self, sha, old):
        if old != self.canonical:
            raise ValueError('simulated_compare_and_swap_failure')
        self.calls.append(('PUSH', sha, old))
        self.canonical = sha

    def writes(self):
        return [call for call in self.calls if call[0] != 'GET']


class PromotionTests(unittest.TestCase):
    def execute(self, api, folder, proof=None):
        return promotion.promote(api, SHA, OLD, ACTOR, proof or evidence(), Path(folder), push=api.push)

    def test_remote_intent_precedes_exact_push_and_single_dispatch(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            result = self.execute(api, folder)
            self.assertEqual(result['run_id'], 99)
            self.assertEqual(result['promotion']['promoted_sha'], SHA)
            self.assertFalse(result['canonical_authority'])
            writes = api.writes()
            self.assertEqual([(a, b) for a, b, _ in writes], [
                ('POST', 'git/trees'), ('POST', 'git/commits'), ('POST', 'git/refs'),
                ('PUSH', SHA), ('POST', 'actions/workflows/' + dispatch.WORKFLOW + '/dispatches')])
            self.assertEqual(writes[-1][2]['inputs'], {'expected_sha': SHA})
            self.assertFalse(api.intent['market_authority'])
            self.assertEqual(api.intent['post_attempts'], 1)

    def test_any_failed_trial_blocks_before_api_or_ref_mutation(self):
        for trial in range(4):
            api = FakeAPI(); proof = evidence(); proof['cohort']['trials'][trial]['passed'] = False
            with self.subTest(trial=trial), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, 'fixed_cohort'):
                    self.execute(api, folder, proof)
                self.assertEqual(api.calls, [])

    def test_every_missing_full_gate_blocks_without_api_or_push(self):
        for gate in dispatch.FULL_GATES:
            api = FakeAPI(); proof = evidence(); proof['build']['gates'].pop(gate)
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, 'complete_build'):
                    self.execute(api, folder, proof)
                self.assertEqual(api.calls, [])

    def test_changed_canonical_predecessor_blocks_before_remote_intent(self):
        api = FakeAPI(); api.canonical = WRONG
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'reference_changed'):
                self.execute(api, folder)
        self.assertEqual(api.writes(), [])

    def test_wrong_actor_sha_rerun_or_event_cannot_promote(self):
        for field, value in [('head_sha', WRONG), ('run_attempt', 2), ('event', 'push'), ('path', 'other')]:
            api = FakeAPI(); api.actor[field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, 'actor_identity'):
                    self.execute(api, folder)
            self.assertEqual(api.writes(), [])

    def test_missing_workflow_registration_blocks_before_canonical_move(self):
        api = FakeAPI(); api.registered = 'disabled_manually'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'not_registered'):
                self.execute(api, folder)
        self.assertEqual(api.writes(), [])

    def test_changed_candidate_workflow_bytes_block_before_claim(self):
        api = FakeAPI(); api.wrong_workflow = True
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'bytes_changed'):
                self.execute(api, folder)
        self.assertEqual(api.writes(), [])

    def test_missing_artifact_bindings_cannot_create_remote_intent(self):
        api = FakeAPI(); proof = evidence(); proof['artifacts'] = {}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'artifact_bindings_missing'):
                self.execute(api, folder, proof)
        self.assertEqual(api.writes(), [])

    def test_remote_intent_from_prior_process_blocks_fresh_local_directory(self):
        api = FakeAPI(); api.claim = 'e' * 40
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'already_consumed'):
                self.execute(api, folder)
        self.assertEqual(api.writes(), [])

    def test_lost_remote_intent_response_never_reaches_push_or_dispatch(self):
        api = FakeAPI(); api.ref_failure = True
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(TimeoutError):
            self.execute(api, folder)
        self.assertEqual([x[:2] for x in api.writes()],
                         [('POST', 'git/trees'), ('POST', 'git/commits'), ('POST', 'git/refs')])
        self.assertEqual(api.canonical, OLD)

    def test_failed_push_consumes_intent_and_never_dispatches_or_retries(self):
        api = FakeAPI()
        def failed_push(*args):
            raise OSError('push response lost')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                promotion.promote(api, SHA, OLD, ACTOR, evidence(), Path(folder), push=failed_push)
        self.assertIsNotNone(api.claim)
        self.assertIsNone(api.run)
        prior_writes = len(api.writes())
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'already_consumed'):
                self.execute(api, folder)
        self.assertEqual(len(api.writes()), prior_writes)

    def test_existing_queued_canonical_run_blocks_even_before_claim(self):
        api = FakeAPI(); api.run = run(); api.run['head_sha'] = WRONG
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'canonical_run_exists'):
                self.execute(api, folder)
        self.assertEqual(api.writes(), [])

    def test_read_only_reconciliation_does_not_promote_missing_run(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                promotion.promote(api, SHA, OLD, ACTOR, evidence(), Path(folder),
                                  push=lambda *_: (_ for _ in ()).throw(OSError('cut')))
            before = len(api.writes())
            result = promotion.reconcile(api, SHA, Path(folder) / 'review')
            self.assertEqual(len(api.writes()), before)
            self.assertIsNone(result['run'])
            self.assertFalse(result['new_post_permitted'])
            self.assertFalse(result['canonical_authority'])

    def test_successful_dispatch_reconciles_by_read_only_identities(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            self.execute(api, folder)
            before = len(api.writes())
            result = promotion.reconcile(api, SHA, Path(folder) / 'review')
            self.assertEqual(result['run']['id'], 99)
            self.assertFalse(result['canonical_authority'])
            self.assertEqual(len(api.writes()), before)

    def test_frozen_environment_mismatch_is_never_qualified(self):
        good = dict(passed=True, failures=[], python=promotion.PYTHON,
                    dependencies=promotion.DEPENDENCIES, policy_predecessor_available=True,
                    canonical_authority=False)
        promotion.verify_environment(good)
        for key, value in [('python', '3.13.5'), ('dependencies', {}), ('failures', ['failure']),
                           ('passed', False), ('policy_predecessor_available', False)]:
            bad = dict(good); bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'environment_not_verified'):
                promotion.verify_environment(bad)

    def test_manual_rerun_or_other_repository_cannot_enter_write_path(self):
        valid = dict(GITHUB_REPOSITORY=promotion.REPOSITORY,
                     GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_ATTEMPT='1')
        with patch.dict(os.environ, valid, clear=True):
            promotion.promotion_environment()
        for field, value in [('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'push'),
                             ('GITHUB_REPOSITORY', 'someone/else')]:
            env = dict(valid); env[field] = value
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                promotion.promotion_environment()

    def test_workflow_routes_only_manual_proofs_to_promotion_then_readonly_review(self):
        text = (promotion.ROOT / promotion.WORKFLOW).read_text()
        self.assertIn('  workflow_dispatch:', text)
        self.assertNotIn('  push:', text)
        self.assertNotIn('schedule:', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('python -m certification.promote_phase_e', text)
        self.assertIn('needs: promote-and-dispatch', text)
        review = text.split('  review-canonical-artifacts:', 1)[1]
        self.assertIn('contents: read', review)
        self.assertIn('actions: read', review)
        self.assertNotIn('actions: write', review)
        self.assertIn('--verify-run "$CANONICAL_RUN"', review)
        self.assertNotIn('MM_SOLANA_READ_RPC_URL', text)
        self.assertNotIn('MM_ROBINHOOD_READ_RPC_URL', text)

    def test_publish_origin_cannot_be_redirected_to_another_repository(self):
        for origin in ('https://example.invalid/receiver.git', '/tmp/local.git',
                       'https://github.com/another/repo.git'):
            with patch.object(promotion.subprocess, 'check_output', return_value=origin):
                with self.assertRaisesRegex(ValueError, 'unapproved_publish_origin'):
                    promotion.require_origin()
        with patch.object(promotion.subprocess, 'check_output',
                          return_value='https://github.com/' + promotion.REPOSITORY + '.git'):
            promotion.require_origin()


class CanonicalReviewTests(unittest.TestCase):
    def prepared(self, folder):
        api = FakeAPI()
        promotion.promote(api, SHA, OLD, ACTOR, evidence(), Path(folder) / 'promotion', push=api.push)
        api.intent['plan_sha256'] = promotion.hashlib.sha256(promotion.PLAN_PATH.read_bytes()).hexdigest()
        return api

    def test_queued_run_never_grants_authority_or_another_post(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); before = len(api.writes())
            result = promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            self.assertFalse(result['passed']); self.assertFalse(result['canonical_authority'])
            self.assertEqual(result['failure'], 'canonical_run_not_terminal_within_review_bound')
            self.assertEqual(len(api.writes()), before)

    def test_failed_run_preserves_artifact_inventory_and_never_grants_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); api.run.update(status='completed', conclusion='failure')
            before = len(api.writes())
            result = promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            self.assertEqual(result['failure'], 'canonical_workflow_failed')
            self.assertFalse(result['canonical_authority'])
            self.assertEqual(result['available_artifacts'], [])
            self.assertEqual(len(result['artifact_recovery']), 2)
            self.assertEqual(len(api.writes()), before)

    def test_green_run_with_invalid_artifacts_stays_uncertified(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); api.run.update(status='completed', conclusion='success')
            with patch.object(promotion, 'collect', side_effect=ValueError('missing raw trial')):
                with self.assertRaises(ValueError):
                    promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            row = promotion.read(Path(folder) / 'review/canonical-review.json')
            self.assertFalse(row['canonical_authority'])
            self.assertEqual(row['failure'], 'canonical_artifact_review_failed')

    def test_full_terminal_evidence_is_required_before_authority_is_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); api.run.update(status='completed', conclusion='success')
            before = len(api.writes()); proof = evidence()
            with patch.object(promotion, 'collect', return_value=proof) as collect:
                result = promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            collect.assert_called_once()
            self.assertTrue(result['passed']); self.assertTrue(result['canonical_authority'])
            self.assertTrue(result['artifacts_verified']); self.assertFalse(result['market_authority'])
            self.assertEqual(len(api.writes()), before)

    def test_changed_cohort_or_canonical_reference_blocks_final_authority(self):
        for changed in ('cohort', 'canonical'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                api = self.prepared(folder); api.run.update(status='completed', conclusion='success')
                proof = evidence()
                if changed == 'cohort':
                    proof['cohort']['trials'][0]['retained_age_peak'] = 999
                else:
                    api.canonical = WRONG
                with patch.object(promotion, 'collect', return_value=proof), self.assertRaises(ValueError):
                    promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
                self.assertFalse(promotion.read(Path(folder) / 'review/canonical-review.json')['canonical_authority'])

    def test_wrong_sha_terminal_run_cannot_be_certified(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); api.run.update(status='completed', conclusion='success', head_sha=WRONG)
            with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
                promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            self.assertFalse(promotion.read(Path(folder) / 'review/canonical-review.json')['canonical_authority'])

    def test_duplicate_post_intent_runs_cannot_receive_final_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.prepared(folder); api.run.update(status='completed', conclusion='success')
            duplicate = dict(api.run, id=100)
            with patch.object(dispatch, 'canonical_runs', return_value=[api.run, duplicate]):
                with self.assertRaisesRegex(ValueError, 'dispatch_not_unique'):
                    promotion.review_canonical(api, SHA, 99, Path(folder) / 'review')
            self.assertFalse(promotion.read(Path(folder) / 'review/canonical-review.json')['canonical_authority'])

    def test_review_bound_is_fixed(self):
        for polls in (0, 361, True):
            with self.assertRaisesRegex(ValueError, 'poll_bound'):
                promotion.review_canonical(FakeAPI(), SHA, 99, Path('unused'), polls=polls)


class RealGitLeaseTests(unittest.TestCase):
    def test_real_compare_and_swap_rejects_a_concurrent_canonical_move(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); local = root / 'local'; remote = root / 'remote.git'
            def git(*args, cwd=local):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
            local.mkdir(); git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
            git('commit', '--allow-empty', '-m', 'base'); base = git('rev-parse', 'HEAD')
            git('commit', '--allow-empty', '-m', 'candidate'); candidate = git('rev-parse', 'HEAD')
            git('init', '--bare', str(remote), cwd=root); git('remote', 'add', 'origin', str(remote))
            git('push', 'origin', f'{base}:refs/heads/{dispatch.BRANCH}')
            with patch.object(promotion, 'ROOT', local):
                with patch('sys.stdout', new_callable=io.StringIO):
                    promotion.push_exact(candidate, base)
            self.assertEqual(git('rev-parse', 'refs/heads/' + dispatch.BRANCH, cwd=remote), candidate)
            git('commit', '--allow-empty', '-m', 'concurrent'); concurrent = git('rev-parse', 'HEAD')
            git('push', 'origin', f'{concurrent}:refs/heads/{dispatch.BRANCH}')
            with patch.object(promotion, 'ROOT', local), self.assertRaises(subprocess.CalledProcessError):
                promotion.push_exact(candidate, base)
            self.assertEqual(git('rev-parse', 'refs/heads/' + dispatch.BRANCH, cwd=remote), concurrent)


class ArtifactPreflightTests(unittest.TestCase):
    def test_incomplete_failed_or_wrong_sha_source_runs_are_rejected(self):
        good = dict(id=10, head_sha=SHA, run_attempt=1, status='completed', conclusion='success')
        for field, value in [('id', 11), ('head_sha', WRONG), ('run_attempt', 2),
                             ('status', 'in_progress'), ('conclusion', 'failure')]:
            row = dict(good); row[field] = value
            api = unittest.mock.Mock(); api.request.return_value = row
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'prerequisite_run'):
                promotion.successful_run(api, 10, SHA)

    def test_missing_skipped_or_duplicate_full_jobs_are_rejected(self):
        good = [dict(name='full / ' + name, status='completed', conclusion='success')
                for name in promotion.CERTIFICATE_JOBS]
        for jobs in (good[:1], good + good[:1], [dict(good[0], conclusion='skipped'), good[1]]):
            with patch.object(promotion, 'all_pages', return_value=jobs), self.assertRaises(ValueError):
                promotion.require_full_jobs(FakeAPI(), 20)

    def test_full_verification_before_cohort_completion_is_rejected(self):
        rows = [dict(id=10, head_sha=SHA, run_attempt=1, status='completed', conclusion='success',
                     updated_at='2026-09-29T02:00:00Z'),
                dict(id=20, head_sha=SHA, run_attempt=1, status='completed', conclusion='success',
                     run_started_at='2026-09-29T01:00:00Z')]
        api = unittest.mock.Mock(); api.request.side_effect = rows
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'verification_order'):
            promotion.collect(api, SHA, 10, 'cohort', 20, Path(folder))
        self.assertEqual([call.args[0] for call in api.request.call_args_list], ['GET', 'GET'])

    def test_same_run_cannot_substitute_for_ordered_independent_full_verification(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'must_follow'):
            promotion.collect(FakeAPI(), SHA, 10, 'cohort', 10, Path(folder))

    def test_aggregate_label_without_environment_and_raw_trials_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'aggregate.json').write_text(json.dumps(accepted()))
            with self.assertRaises(FileNotFoundError):
                promotion.verify_evidence(root, root, SHA, root / 'out')

    def fixture(self, root):
        from certification.tests.test_final_acceptance import FinalAcceptanceTests
        FinalAcceptanceTests().build(root)
        for path in root.rglob('*.json'):
            value = json.loads(path.read_text())
            def replace(item):
                if isinstance(item, dict): return {k: replace(v) for k, v in item.items()}
                if isinstance(item, list): return [replace(v) for v in item]
                return SHA if item == 'sha' else item
            path.write_text(json.dumps(replace(value)))
        offline = promotion.read(root / 'offline/result.json')
        spec = promotion.manifest()
        offline.update(implementation_hash=promotion.implementation_hash(),
                       source_manifest_hash=promotion.digest(spec),
                       source_diff_hashes={lane: row['source_diff_sha256'] for lane, row in spec['lanes'].items()})
        (root / 'offline/result.json').write_text(json.dumps(offline))
        registry = promotion.read(promotion.ROOT / 'certification/historical_exposure.json')
        historical = promotion.read(root / 'historical-resolution.json')
        historical['receipt_sha256'] = registry['resolved'][0]['resolution']['receipt_sha256']
        (root / 'historical-resolution.json').write_text(json.dumps(historical))
        (root / 'directional-acceptance').mkdir()
        (root / 'directional-acceptance/result.json').write_text(json.dumps(dict(passed=True, integration_sha=SHA)))
        (root / 'preserved-validation.json').write_text(json.dumps(dict(
            passed=True, integration_sha=SHA, fresh_market_data_used=False)))
        from certification.final_acceptance import run as final_run
        final_run(root, root / 'final-acceptance.json', SHA, preserved_only=True)

    def test_raw_machinery_recomputation_rejects_a_forged_green_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); build_root = root / 'build'; build_root.mkdir(); self.fixture(build_root)
            cohort = root / 'cohort'; cohort.mkdir()
            (cohort / 'environment.json').write_text(json.dumps(dict(
                passed=True, failures=[], python=promotion.PYTHON, dependencies=promotion.DEPENDENCIES,
                policy_predecessor_available=True, canonical_authority=False)))
            from certification import cleanup_recovery
            accepted_cohort = accepted()
            accepted_cohort['plan_sha256'] = promotion.hashlib.sha256(promotion.PLAN_PATH.read_bytes()).hexdigest()
            with patch.object(cleanup_recovery, 'aggregate', return_value=accepted_cohort):
                validated, _ = promotion.verify_evidence(cohort, build_root, SHA, root / 'first-review')
                self.assertTrue(validated['passed'])
                # Leave final-acceptance.json green; corrupt a required raw result.
                (build_root / 'restart-safety/result.json').write_text(json.dumps(dict(passed=False)))
                with self.assertRaisesRegex(ValueError, 'complete_acceptance_changed'):
                    promotion.verify_evidence(cohort, build_root, SHA, root / 'second-review')

    def test_exact_240_second_age_fails_the_canonical_pressure_gate(self):
        from certification.final_acceptance import run as final_run
        for field in ('oldest_hot_age_peak', 'oldest_retained_age_peak'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); self.fixture(root)
                path = root / 'run381-pressure/result.json'; row = promotion.read(path)
                row[field] = 240; path.write_text(json.dumps(row))
                self.assertEqual(final_run(root, root / 'recomputed.json', SHA, preserved_only=True), 1)
                self.assertFalse(promotion.read(root / 'recomputed.json')['gates']['mature_solana_pressure'])


if __name__ == '__main__':
    unittest.main()
