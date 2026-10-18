"""Actual child ownership + native source COMMITs over synthetic provider wire.

Root/unit/native-clock acquisition premises are simulated by the existing
prewrite fixture. This is not an authenticated live market or readiness proof.
"""
import json
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_pons_boot as pons
from meme_machine.solana_selective_source import SelectiveSource
from tests import test_normal_pons_boot as owner_fixture
from tests.test_pons_native_work import owner_child_script


NATIVE_SOURCE=r'''
        from pathlib import Path
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_historical import Preparation,PLAN
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
        from meme_machine.lanes.pons.provider_admission import fingerprint
        from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts,validated
        endpoint='https://robinhood-mainnet.g.alchemy.com/v2/OWNED_SYNTHETIC_NO_CREDENTIAL'
        meter=PonsEconomicCohorts('actual-child-synthetic-wire',endpoint,native_owner=cap)
        assert validated(meter,endpoint) is meter
        assert meter.meter.binding['source_generation']=='UNESTABLISHED'
        assert meter.meter.binding['native_owner_identity_sha256']==cap.identity_sha256
        tape=Tape(candidates=0);tape.provider_fingerprint=fingerprint(endpoint)
        history=PonsHistory(Path(cap.identity()['root'])/'pons-owner-source.sqlite',
            policy=POLICY_HASH,economic_cohorts=meter)
        try:
            prep=Preparation(history,tape.provider,clock=lambda:int(tape.header(tape.top)['timestamp'],16)+1)
            prep.begin()
            for _ in range(100):
                plan=history.get_meta(PLAN)
                if 'first' not in plan:prep.boundary_step()
                elif prep._frontier('population',plan['first'],plan['anchor'])['block']<tape.top:prep.discover_step()
                else:break
            assert prep.resume()['ready']
            initial=meter.membership.snapshot()
            assert initial['factory_domain_installed']
            tape.top+=1;prep.extend(tape.header(tape.top));assert prep.discover_step()
            observed=meter.snapshot()
            assert observed['source_membership']['committed_factory_bridges']==1
            assert observed['source_membership']['factory_through']==tape.top
            assert observed['native_owner_identity_sha256']==cap.identity_sha256
            assert observed['native_owner_provenance']=='SEALED_SUPERVISOR_PONS_OWNER_ONLY'
            assert observed['source_membership']['owner_provenance']=='SEALED_SUPERVISOR_PONS_OWNER_NOT_CANONICAL_SOURCE_GENERATION'
            assert not observed['source_membership']['full_universe_complete']
            assert observed['source_membership']['held_membership']=='UNESTABLISHED'
            assert not history.db.in_transaction
        finally:history.close()
'''


class PonsOwnerSourceBindingTests(unittest.TestCase):
    def test_real_private_owner_and_factory_commit_compose_without_source_or_held_authority(self):
        case=owner_fixture.NativePonsOwnerTests();case.setUp();self.addCleanup(case.doCleanups)
        script=owner_child_script(NATIVE_SOURCE)
        script=script.replace('        cap.close();assert pons.current_pons_owner_context() is None\n',
            '        cap.close();assert pons.current_pons_owner_context() is None\n'
            "        assert meter.snapshot()['state']=='UNKNOWN'\n")
        channel=pons.PonsOwnerLaunch(case.context)
        with patch.object(owner_fixture,'CHILD',script):child=case.launch(channel)
        value=case.bind(channel,child);raw=child.stdout.readline()
        self.assertTrue(raw,child.stderr.read() if child.poll() is not None else 'child closed stdout')
        row=json.loads(raw)
        self.assertEqual(row['identity_sha256'],pons.digest(value))
        self.assertTrue(row['closed_refuses']);case.finish(child)

    def test_normal_source_and_isolated_source_capabilities_cannot_mix_before_constructors(self):
        for field in ('native_resources','native_ports'):
            with self.subTest(field=field),patch(
                    'meme_machine.operational.normal_source_boot.require_native_generation',
                    side_effect=AssertionError('private normal check not reached')) as checked:
                with self.assertRaisesRegex(ValueError,'normal_source_isolated_resources_conflict'):
                    SelectiveSource(object(),object(),normal_generation=object(),**{field:object()})
                checked.assert_not_called()
