import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.operational.configuration import environment,capture,UNITS


class Configuration(unittest.TestCase):
    def test_manifest_contains_names_and_public_endpoint_identity_without_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'paper.env'
            path.write_text('MM_MODE=PAPER\nMM_STATE_ROOT=/mnt/volume/state\nMM_ROBINHOOD_READ_RPC_URL=https://example.com/v2/never-publish-this-key\nPROVIDER_TOKEN=another-secret\n')
            value=environment(path);raw=json.dumps(value)
            self.assertNotIn('never-publish-this-key',raw);self.assertNotIn('another-secret',raw)
            self.assertIn('PROVIDER_TOKEN',value['variable_names'])
            self.assertEqual(value['provider_endpoints']['MM_ROBINHOOD_READ_RPC_URL']['hostname'],'example.com')
            self.assertNotIn('environment_sha256',value)

    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);source=root/'source';source.mkdir()
        (source/'requirements.txt').write_text('')
        config=root/'config';config.mkdir();units=root/'units';units.mkdir()
        for suffix in UNITS:(units/('meme-machine-'+suffix)).write_text('[Service]\n')
        device=root/'device';device.touch()
        for name,epoch in (('','paper-historical-500'),('.shared-1000','paper-separate-1000')):
            state=root/epoch
            (config/('paper'+name+'.env')).write_text(
                f'MM_STATE_ROOT={state}\nMM_SOLANA_READ_RPC_URL=https://example.com/v2/private-key\n')
            (config/('storage'+name+'.json')).write_text(json.dumps(
                dict(state_root=str(state),epoch_id=epoch,volume_device=str(device))))
        (config/'digitalocean.env').write_text('DO_TOKEN=private-admin-token\n')
        (config/'backup.json').write_text('{}')
        return source,config,units

    def inspect(self,source,config,units,env):
        def git(args,**_):
            return '' if args[1]=='status' else ('a'*40 if args[-1]=='HEAD' else 'b'*40)
        with patch('meme_machine.operational.configuration.subprocess.check_output',side_effect=git):
            return capture(source,configuration_root=config,unit_root=units,environ=env)

    def test_historical_default_and_explicit_new_epoch_have_distinct_acceptance_identity(self):
        source,config,units=self.fixture()
        old=self.inspect(source,config,units,{})
        env=dict(MM_PAPER_ENV_FILE=str(config/'paper.shared-1000.env'),
                 MM_STORAGE_GUARD_CONFIG=str(config/'storage.shared-1000.json'),
                 MM_STATE_ROOT=str(config.parent/'paper-separate-1000'))
        new=self.inspect(source,config,units,env)
        self.assertEqual(old['storage']['epoch_id'],'paper-historical-500')
        self.assertEqual(new['storage']['epoch_id'],'paper-separate-1000')
        self.assertEqual(new['environment']['public_values']['MM_STATE_ROOT'],env['MM_STATE_ROOT'])
        self.assertEqual(new['configuration_files']['paper'],env['MM_PAPER_ENV_FILE'])
        self.assertNotIn('private-key',json.dumps(new))
        self.assertNotIn('private-admin-token',json.dumps(new))
        self.assertNotEqual(old['configuration_files'],new['configuration_files'])
        self.assertEqual(new['paper_policy']['policy_revision'],'paper-opportunity-access-v1')
        self.assertFalse(new['paper_policy']['portfolio_epoch_changed'])
        self.assertFalse(new['paper_policy']['financial_policy_changed'])
        self.assertEqual(set(new['paper_policy']['regime_policy_hashes']),
            {'pump_current','pump_survivor','pons_current','pons_survivor'})

    def test_unsupported_policy_selection_cannot_masquerade_as_the_active_revision(self):
        source,config,units=self.fixture()
        with self.assertRaisesRegex(ValueError,'unsupported_paper_policy_revision'):
            self.inspect(source,config,units,{'MM_PAPER_POLICY_REVISION':'research-only-policy'})

    def test_new_epoch_capture_cannot_fall_back_to_old_guard_or_missing_environment(self):
        source,config,units=self.fixture()
        env=dict(MM_PAPER_ENV_FILE=str(config/'paper.shared-1000.env'),
                 MM_STATE_ROOT=str(config.parent/'paper-separate-1000'))
        with self.assertRaisesRegex(ValueError,'acceptance_configuration_state_root_mismatch'):
            self.inspect(source,config,units,env)
        env['MM_STORAGE_GUARD_CONFIG']=str(config/'storage.shared-1000.json')
        (config/'paper.shared-1000.env').unlink()
        with self.assertRaises(FileNotFoundError):self.inspect(source,config,units,env)
