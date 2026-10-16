"""Selected PAPER decision revision; portfolio epoch/accounting stay independent."""
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os

ACTIVE_REVISION = 'paper-opportunity-access-v1'
PREVIOUS_REVISION = 'pre-paper-opportunity-access-v1'
PREVIOUS_SOURCE = 'a048ee8cbeb87bff9c589a0b6f587fd909c23ed5'
PREVIOUS_SNAPSHOT_SHA256 = '9e30348778689f945f0a3faa18b7b45a3badbdda207ab38966dc1c91d7ec2303'

# Exact hashes of the already-published opportunity-access Survivors, before
# structural re-entry. These are recovery/flat-transition identities ONLY.
# They never authorize new decisions or restore the previous entry predicate.
SUPERSEDED_ACTIVE_SURVIVOR_HASHES = {
    'pump_survivor': 'e4c0517e3284a18ce0e38feb79915b4220227efa6ff41fcaffb30d9dc8eecae9',
    'pons_survivor': '34f968df79aabef6e8fefaf022c69e2abbc334bfd18eff509d48cbbefff66ac4',
}


@lru_cache(maxsize=1)
def _previous_policies():
    """Read the immutable reviewed policy snapshot, never operating state."""
    path=Path(__file__).with_name('policy_history')/'pre_opportunity_access_v1.json'
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PREVIOUS_SNAPSHOT_SHA256:
        raise ValueError('previous_paper_policy_snapshot_integrity')
    value=json.loads(raw)
    if value.get('revision')!=PREVIOUS_REVISION or value.get('source_commit')!=PREVIOUS_SOURCE:
        raise ValueError('previous_paper_policy_snapshot_identity')
    for facts in value['regimes'].values():
        encoded=json.dumps(facts['policy'],sort_keys=True,separators=(',',':')).encode()
        if hashlib.sha256(encoded).hexdigest()!=facts['policy_hash']:
            raise ValueError('previous_paper_policy_hash')
    return value['regimes']


def previous_policies():
    return deepcopy(_previous_policies())


def previous_hash(regime):
    return _previous_policies()[regime]['policy_hash']


def current_hashes():
    from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash
    from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH as pump_survivor
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as pons_current
    from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH as pons_survivor
    return dict(pump_current=policy_hash(),pump_survivor=pump_survivor,
        pons_current=pons_current,pons_survivor=pons_survivor)


def selected_revision(environ=None):
    value=(os.environ if environ is None else environ).get('MM_PAPER_POLICY_REVISION',ACTIVE_REVISION)
    if value!=ACTIVE_REVISION:raise ValueError('unsupported_paper_policy_revision')
    return value


def decision_metadata(environ=None):
    return dict(policy_revision=selected_revision(environ),regime_policy_hashes=current_hashes(),
        previous_revision=PREVIOUS_REVISION,previous_source=PREVIOUS_SOURCE,
        portfolio_epoch_changed=False,financial_policy_changed=False)


def revision_for_hash(policy_hash):
    if policy_hash in current_hashes().values() or policy_hash in SUPERSEDED_ACTIVE_SURVIVOR_HASHES.values():return ACTIVE_REVISION
    if policy_hash in (value['policy_hash'] for value in _previous_policies().values()):return PREVIOUS_REVISION
    return None
