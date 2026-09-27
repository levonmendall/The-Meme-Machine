"""Prior authorized windows cannot consume the next window's observation budget."""
import unittest
from certification.tests import test_survivor_candidate_progress as launcher

PONS=r'''
from unittest.mock import patch
from robinhood_research import pons_selective_cohort as native
from robinhood_tests.test_pons_continuous_campaign import ContinuousCampaignTests
checkpoint=native._checkpoint;injected=[]
def prior_window(result,**kwargs):
 if not injected:
  # Complete preserved predecessor observations; trial/qualifier indices stay
  # cumulative. The separate real capsule/recovery test proves this offset's
  # authorization and persistence. Only the scheduling seam is isolated here.
  assert not result['rows'] and not result['qualifiers']
  result['rows']=[dict(index=i,curve='old',live_authorization='rejected') for i in range(native.MAX_ENROLLED)]
  result['autonomous_observation_offset']=native.MAX_ENROLLED
  injected.append(True)
 return checkpoint(result,**kwargs)
with patch.object(native,'_checkpoint',side_effect=prior_window):
 ContinuousCampaignTests().test_discovery_failure_drains_admitted_future_and_initializes_one_book()
assert injected
print('native new-window hydration and lifecycle dispatch proceed with 20,000 preserved predecessor rows')
'''
class PonsWindowCapacityTests(unittest.TestCase):
    run_native=launcher.SurvivorCandidateProgressTests.run_native
    def test_previous_window_does_not_permanently_exhaust_next_window(self):
        self.run_native(PONS,lanes=('pons',))
