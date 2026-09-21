"""Small accounting receipts in Actions logs supplement, never replace, raw artifacts."""
import hashlib
import json
import re

def boundary(value):
    if not isinstance(value,str):return None
    safe=re.fullmatch(r'(?:(?:provider_recovery_exhausted|selective_position_provider_recovery_exhausted):)?provider_(?:shared_admission_deadline|shared_queue_capacity|session_budget_exhausted|pool_budget_exhausted|transport_failure|http_[0-9]+|rpc_-?[0-9]+)',value)
    return dict(kind=value if safe else 'unclassified_boundary',
                sha256=hashlib.sha256(value.encode()).hexdigest())

def emit_pons(report,emit=print):
    scalar=lambda row,names:{k:row[k] for k in names if k in row and (row[k] is None or type(row[k]) in (int,bool))}
    cohort=report.get('cohort_accounting') or {}
    emit('PAPER_TERMINAL_RECEIPT '+json.dumps(dict(lane='pons',kind='cohort',
        boundary=boundary(report.get('boundary')),
        accounting=scalar(cohort,('cash','remaining_cost_basis','reserved','realized','unsettled',
            'native_execution_cost','conservation','cash_basis_conservation','capital_integral_complete')),
        raw_artifact_required_for_replay=True),sort_keys=True),flush=True)
    for life in report.get('lifecycles',[]):
        position=life.get('final_position') or {}
        identity=life.get('lifecycle_id') or position.get('id')
        valid=isinstance(identity,str) and re.fullmatch(r'pons-selective:[0-9a-f-]{36}:0x[0-9a-fA-F]{40}:0x[0-9a-fA-F]{64}',identity)
        status=life.get('status')
        emit('PAPER_TERMINAL_RECEIPT '+json.dumps(dict(lane='pons',kind='lifecycle',
            index=life.get('index') if type(life.get('index')) is int else None,
            lifecycle_id=identity if valid else None,
            identity_sha256=hashlib.sha256(str(identity).encode()).hexdigest(),
            status=status if status in ('settled','boundary','entry_failed','capacity_censored','unexpected_boundary') else 'unknown',
            boundary=boundary(life.get('boundary')),
            liquidity_writeoff=life.get('settlement_kind')=='liquidity_writeoff',
            position=scalar(position,('tokens','cost','realized_proceeds','realized','pnl','last_at','version')),
            realized_pnl_quote=life.get('realized_pnl_quote') if type(life.get('realized_pnl_quote')) is int else None,
            raw_artifact_required_for_replay=True),sort_keys=True),flush=True)
