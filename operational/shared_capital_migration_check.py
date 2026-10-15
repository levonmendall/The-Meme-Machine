"""Verify the known empty preserved epoch, using the existing migration/backup APIs.

This is an isolated validator, never an operational migration or activation CLI.
Nonempty economic inventories require their complete native mapping first.
"""
from contextlib import closing
from pathlib import Path
import argparse
import json
import sqlite3
from decimal import Decimal


def check(backup,isolated,policy,output):
    from operational.tests import network_guard
    network_guard()
    from meme_machine.operational.backup import prove_replay,state_identity,copy_state,verify_copy,require_isolated
    from meme_machine.portfolio_accounting import _decode_checkpoint
    from meme_machine.shared_capital.runtime import RuntimeCapital
    from meme_machine.shared_capital.operational_candidate import prepare_plan
    from meme_machine.shared_capital.model import REGIMES,digest
    from meme_machine.runtime.directional_sleeve import policies
    from meme_machine.shared_capital.cutover import install,rollback_unused
    backup=require_isolated(backup);isolated=require_isolated(isolated);before=state_identity(backup)
    old=_decode_checkpoint(before['replayed_state']);verify_copy(backup);prove_replay(backup)
    if (old['positions'] or old['reservations'] or before['pending_deliveries'] or before['native_ids'] or old['native_cursors']
            or any(v['count'] or v['realized_pnl'] or v['fees'] for v in old['retired'].values()) or old['shared_costs']):
        raise RuntimeError('nonempty_epoch_requires_complete_native_inventory_mapping')
    contracts={f:dict(strategy_id=f,policy_hash=old['identities']['lanes'][f]['policy_hash']) for f in ('meteora','ramses')}
    for family in ('pump','pons'):
        for strategy,policy_hash in policies(family).items():
            contracts[family+('_survivor' if 'survivor' in strategy else '_current')]=dict(strategy_id=strategy,policy_hash=policy_hash)
    mapping=dict(contracts=contracts,position_meta={},reservation_meta={},retired={r:dict(pnl='0',costs='0',count=0) for r in REGIMES},
        pending={},cursor_mapping={},obligations={})
    plan=prepare_plan(backup/'portfolio.sqlite',mapping,policy=policy)
    copy_state(backup,isolated,seconds=120)
    # Offline test flags describe this disposable transactional simulation.
    # They are never evidence of deployment or live provider prerequisites.
    prerequisites={k:True for k in ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')}
    marker=install(isolated,plan,approved_policy=plan['policy'],prerequisites=prerequisites)
    if install(isolated,plan,approved_policy=plan['policy'],prerequisites=prerequisites)!=marker:raise RuntimeError('selection_not_idempotent')
    with closing(RuntimeCapital(isolated/'shared-capital.sqlite')) as authority:
        first=authority.install_migration(plan);second=authority.install_migration(plan)
        if first!=second:raise RuntimeError('migration_not_idempotent')
        proof=authority.verify_replay();capital=authority.snapshot()['capital']
        if Decimal(capital['actual_cash'])!=500 or Decimal(capital['deployed_basis'])!=0:raise RuntimeError('capital_changed')
    with closing(RuntimeCapital(isolated/'shared-capital.sqlite')) as authority:
        if authority.verify_replay()!=proof:raise RuntimeError('restart_replay_changed')
    recovery=prove_replay(isolated)
    with sqlite3.connect(isolated/'portfolio.sqlite') as db:
        try:db.execute('DELETE FROM portfolio_events')
        except sqlite3.IntegrityError as error:
            if str(error)!='legacy_funding_authority_retired':raise
        else:raise RuntimeError('older_writer_not_fenced')
    rollback_unused(isolated)
    if state_identity(isolated)!=before or state_identity(backup)!=before:raise RuntimeError('preserved_epoch_changed')
    result=dict(schema='actual-preserved-epoch-offline-migration-v1',classification='VERIFIED_ISOLATED_ACTUAL_EPOCH',
        epoch_id=plan['seed']['epoch_id'],inception_sha256=plan['seed']['inception_sha256'],source_sequence=plan['source']['sequence'],
        source_journal_hash=plan['source']['journal_hash'],source_replayed_sha256=plan['source']['replayed_sha256'],
        migration_sha256=plan['migration_sha256'],proposal_policy_sha256=digest(plan['policy']),native_mapping_sha256=digest(mapping),
        positions=0,reservations=0,pending_deliveries=0,funding_obligations=0,native_ids=0,native_cursors=0,
        shared_capital=capital,migration_replay=proof,idempotent_migration=True,restart_replay=True,
        exclusive_selection_and_older_sql_fence=True,identical_selection_idempotent=True,unused_rollback_preserves_epoch=True,
        backup_unchanged=True,deployed_epoch_modified=False,isolated_shared_backup_replay=recovery,
        independent_off_host_backup_verified=False,provider_proof_verified=False,risk_caps_approved=False,
        cutover_status='OFFLINE_VALIDATED_NOT_ACTIVATED')
    output.mkdir(exist_ok=True,parents=True)
    (output/'MIGRATION.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'NATIVE_MAPPING.json').write_text(json.dumps(mapping,indent=2,sort_keys=True)+'\n')
    (isolated.parent/'actual-epoch-migration-plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')


def main():
    from meme_machine.shared_capital import RiskPolicy
    p=argparse.ArgumentParser();p.add_argument('--backup',required=True);p.add_argument('--isolated',required=True)
    p.add_argument('--policy',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    check(Path(a.backup),Path(a.isolated),RiskPolicy(**json.loads(Path(a.policy).read_text())),Path(a.output))


if __name__=='__main__':main()
