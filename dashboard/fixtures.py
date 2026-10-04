"""Deterministic synthetic USD accounting, never imported in canonical mode."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from .model import canonical, inception_receipt, LANES

FIXTURE_NOW = 1790247600  # fixed clock; not an inferred production inception


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def example():
    epoch = inception_receipt('fixture-500-v1', iso(FIXTURE_NOW-86400), 'synthetic-inception-001')
    positions = []
    # One lifecycle each: wins, losses, true breakevens, harvest/runner and maker.
    results = ('4.21', '-1.00', '0.00', '2.80', '-0.40', '2.00', '-0.55', '0.40')
    for i, result in enumerate(results):
        lane = LANES[i//2]
        entry, settlement = iso(FIXTURE_NOW-70000+i*6500), iso(FIXTURE_NOW-68000+i*6500)
        positions.append(dict(epoch_id=epoch['epoch_id'], id=f'fixture-{lane}-{i}', lane=lane,
            asset=('NOVA-SOL', 'EMBER-SOL', 'PONS-ETH', 'PONS-USD', 'RAM-USDC', 'RAM-ETH', 'SOL-USDC', 'ORBIT-SOL')[i],
            exposure_entered=True, state='SETTLED', entered_at=entry, settled_at=settlement,
            capital='25.00', remaining_basis='0.00', realized_pnl=result, fees='0.10', gross_result=str(Decimal(result)+Decimal('.10')),
            entry_value='25.00', exit_value=str(Decimal('25')+Decimal(result)), strategy_id=f'{lane}-fixture-policy',
            source_sha='a'*40, policy_hash='b'*64, config_hash='c'*64, exit_reason='canonical_exit',
            lifecycle=[dict(stage='paper_entry', at=entry), dict(stage='settlement', at=settlement)]))
    for i, lane in enumerate(LANES):
        entry = iso(FIXTURE_NOW-1200-i*100)
        row = dict(epoch_id=epoch['epoch_id'], id=f'fixture-open-{lane}', lane=lane,
            asset=('ARC-SOL', 'AURA-ETH', 'RAM-USDC', 'SOL-USDC')[i], exposure_entered=True,
            state='OPEN', entered_at=entry, capital='25.00', remaining_basis='20.00' if lane=='pons' else '25.00',
            realized_pnl='1.00' if lane=='pons' else '0.00', fees='0.05', entry_value='25.00',
            strategy_id=f'{lane}-fixture-policy', source_sha='a'*40, policy_hash='b'*64,
            mark=dict(state='CURRENT', net_liquidation_value=('26.50','20.60','26.00','25.90')[i],
                      as_of=iso(FIXTURE_NOW-1), valid_until=iso(FIXTURE_NOW+4)),
            lifecycle=[dict(stage='paper_entry', at=entry), dict(stage='monitoring', at=iso(FIXTURE_NOW-1))])
        if lane=='pons':
            row.update(harvest_state='HARVESTED', runner_state='ACTIVE', remaining_runner_exposure='20.00')
            row['lifecycle'].insert(1, dict(stage='partial_realization', at=iso(FIXTURE_NOW-500)))
        if lane in ('ramses', 'meteora'):
            row.update(lp_state='MAKER_ACTIVE', range_id='range-100-152', in_range=True, rebalance_count=2, rebalance_state='MONITORING')
        positions.append(row)
    realized = sum(Decimal(p['realized_pnl']) for p in positions)
    shared = Decimal('.12')
    realized -= shared
    deployed = sum(Decimal(p['remaining_basis']) for p in positions)
    unrealized = sum(Decimal(p['mark']['net_liquidation_value'])-Decimal(p['remaining_basis']) for p in positions if p['state']=='OPEN')
    equity = Decimal('500')+realized+unrealized
    histories = []
    # Actual synthetic samples, including a visible drawdown. No random generator.
    for index, delta in enumerate(('0','1.20','0.40','3.10','2.20','5.50','4.00','7.50',str(equity-500))):
        at = iso(FIXTURE_NOW-86400+index*10800)
        histories.append(dict(epoch_id=epoch['epoch_id'], series='portfolio', at=at, value=str(500+Decimal(delta))))
    for lane in LANES:
        histories.extend([dict(epoch_id=epoch['epoch_id'], series=lane, at=epoch['inception_at'], value='0'),
            dict(epoch_id=epoch['epoch_id'], series=lane, at=iso(FIXTURE_NOW), value=str(sum(Decimal(p['realized_pnl'])+(Decimal(p['mark']['net_liquidation_value'])-Decimal(p['remaining_basis']) if p['state']=='OPEN' else 0) for p in positions if p['lane']==lane)))])
    export = dict(schema='meme-machine-portfolio-export-v1', mode='fixture', epoch_id=epoch['epoch_id'],
        inception_sha256=hashlib.sha256(canonical(epoch).encode()).hexdigest(), sequence=1,
        as_of=iso(FIXTURE_NOW), valid_until=iso(FIXTURE_NOW+4), complete_lifecycle_coverage=True,
        balances=dict(equity=str(equity), available_cash=str(500+realized-deployed-10), reserved_cash='10.00',
            deployed_capital=str(deployed), realized_pnl=str(realized), fees='1.12', shared_costs=str(shared)),
        positions=positions, history=histories, history_complete=True, source_sha='a'*40, config_hash='c'*64)
    telemetry = dict(observed_at=FIXTURE_NOW, lanes={lane: dict(health='responsive', accounting_reconciled=True,
        policy_hash='b'*64, provider_requests=120+i*20, progress_age_seconds=2) for i,lane in enumerate(LANES)})
    telemetry['lanes']['meteora']['health'] = 'progress_stalled'
    return epoch, export, telemetry


def write(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for name, data in zip(('inception', 'accounting', 'telemetry'), example()):
        # Fixtures never overwrite any existing file, including canonical input.
        with (root/(name+'.json')).open('x') as file:
            json.dump(data, file, indent=2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    write(parser.parse_args().directory)
