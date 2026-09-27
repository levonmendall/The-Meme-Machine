import unittest
from unittest.mock import patch
from certification import lifecycle_identity as ids


class LifecycleIdentityTests(unittest.TestCase):
    def test_exact_window_binding_preserves_prefix_and_rejects_archived_reentry(self):
        first=dict(campaign_id='churn-fixture',authorization_hash='a'*64,index=1)
        with patch('certification.campaign_state.active_window',return_value=first):
            identity=ids.issue('run:candidate:regime');ids.validate_new(identity)
        self.assertTrue(identity.startswith('run:candidate:regime:'))
        archived=dict(campaign=ids.scope(first)['campaign'],through=1)
        for window in (None,dict(first,index=2),dict(first,authorization_hash='b'*64)):
            with patch('certification.campaign_state.active_window',return_value=window),self.assertRaises(ValueError):
                ids.validate_new(identity,archived=archived)
        with patch('certification.campaign_state.active_window',return_value=dict(first,index=2)):
            fresh=ids.issue('run:candidate:new-regime');ids.validate_new(fresh,archived=archived)
            with self.assertRaises(ValueError):ids.validate_new('run:candidate:regime',archived=archived)
        with patch('certification.campaign_state.active_window',return_value=first),self.assertRaisesRegex(ValueError,'archived_lifecycle_replay'):
            ids.validate_new(identity,archived=archived)

    def test_legacy_and_read_only_position_ids_are_not_rewritten(self):
        with patch('certification.campaign_state.active_window',return_value=None):
            self.assertEqual(ids.issue('existing-position'),'existing-position')
            ids.validate_new('existing-position')
        for identity in ('x'+ids.MARKER+'a'*64+':01','x'+ids.MARKER+'bad:1'):
            with self.assertRaises(ValueError):ids.parsed(identity)
