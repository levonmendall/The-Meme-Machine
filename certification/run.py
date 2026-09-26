"""Reproducible pinned-worktree verification and concurrent live-paper supervisor."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from certification.journal import canonical,digest,Journal
from certification.governor import Governor
from certification.solana_efficiency import SolanaReuseView
from certification.pressure import PressureView, ReuseView
from certification.report import LANES,dashboard,evaluate,summarize,pipeline_health,provider_efficiency
from certification.controls import (audit_telemetry,broker_snapshot,record_unfinished_broker_jobs,
                                    hourly_engineering,smoke_engineering,sustained_readiness)

ROOT=Path(__file__).resolve().parents[1]
REPORTS={'pump':'pump-acceleration-natural-prospective.json','meteora':'solana-dlmm-independent-v1-live.json',
         'pons':'pons-selective-continuation-v1-cohort.json','ramses':'robinhood-ramses-extended-market-report.json'}


def atomic(path,data):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(canonical(data)+'\n');os.replace(temp,path)


def publish_dashboard(result,path):
    """Diagnostic rendering has no authority over independent lane processes."""
    try:
        dashboard(result,path)
        return dict(published=True,error=None)
    except Exception as exc:
        return dict(published=False,error=type(exc).__name__)


def git(*args,cwd=ROOT):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()


def manifest():return json.loads((ROOT/'certification/sources.json').read_text())


def historical_exposure():
    """Return only admission-blocking historical exposure.

    Resolved rows are retained permanently with a digest-pinned proof receipt.
    A resolution never mutates the original artifact or fabricates market settlement.
    """
    registry=json.loads((ROOT/'certification/historical_exposure.json').read_text())
    if (registry.get('schema_version')!=1
            or not isinstance(registry.get('unresolved'),list)
            or not isinstance(registry.get('resolved',[]),list)):
        raise ValueError('historical_exposure_registry_invalid')
    for row in registry['unresolved']:
        if row.get('lane') not in LANES or row.get('resolution') is not None:
            raise ValueError('historical_exposure_resolution_requires_verified_recovery')
        if type(row.get('observed_open_positions')) is not int or row['observed_open_positions']<1:
            raise ValueError('historical_exposure_inventory_invalid')
    for row in registry.get('resolved',[]):
        proof=row.get('resolution')
        if (row.get('lane') not in LANES or not isinstance(proof,dict)
                or proof.get('disposition')!='certified_historical_unreplayable_zero_proceeds_writeoff'
                or proof.get('immutable_original_artifact_preserved') is not True
                or proof.get('market_settlement_performed') is not False
                or proof.get('proceeds_lamports')!=0
                or proof.get('open_positions_after')!=0
                or proof.get('reserved_after')!=0
                or proof.get('stale_marks_after')!=0
                or proof.get('writeoffs_after')!=1
                or not isinstance(proof.get('receipt_sha256'),str)
                or len(proof['receipt_sha256'])!=64):
            raise ValueError('historical_exposure_resolution_receipt_invalid')
    return registry['unresolved']


def implementation_hash():
    files=sorted(p for p in (ROOT/'certification').rglob('*') if p.is_file() and p.suffix in ('.py','.json','.patch'))
    return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def canonical_patch_bytes(value):
    """Normalize non-semantic Git blob-id metadata while preserving the exact patch."""
    if not isinstance(value,(bytes,bytearray)):
        raise TypeError('patch_bytes_required')
    # The right-hand blob id in an "index old..new" line is derived from the
    # patched result and changes whenever a reviewed insertion changes. It is not
    # execution content. Keep modes, paths, hunks and every added/removed byte exact.
    return re.sub(rb'(?m)^index [0-9a-f]+\.\.[0-9a-f]+(?=(?: [0-7]{6})?$)',
                  b'index <blob>..<blob>',bytes(value))


LANE_PATCHES={
    'pump':('pump-accounting.patch','market-scope-efficiency-pump.patch'),
    'meteora':('meteora-checkpoint.patch','market-scope-efficiency-meteora.patch'),
    'pons':('pons-cohort-capital.patch','market-scope-efficiency-pons.patch'),
    'ramses':('ramses-admission.patch','market-scope-efficiency-ramses.patch'),
}

def lane_patches(lane,row=None):
    declared=(row or {}).get('overlay_patches')
    if declared is not None:
        return [ROOT/p for p in declared]
    return [ROOT/'certification'/'patches'/name for name in LANE_PATCHES.get(lane,())]


def source_integrity(worktrees):
    observed={}
    for lane,row in manifest()['lanes'].items():
        cwd=Path(worktrees)/lane
        # git diff omits untracked and ignored files. Such a module can shadow a
        # pinned import while all tracked source/overlay hashes still match.
        extras=subprocess.check_output(['git','ls-files','--others','-z'],cwd=cwd).decode().split('\0')
        for name in filter(None,extras):
            path=Path(name)
            if path.suffix.lower() in ('.py','.pyw','.so','.pyd','.pth') or name in ('.env','config.local.json'):
                raise ValueError('unreviewed_lane_runtime_file:'+lane+':'+name)
            if path.suffix.lower()=='.pyc' and '__pycache__' not in path.parts:
                raise ValueError('unreviewed_lane_runtime_file:'+lane+':'+name)
        if git('rev-parse','HEAD',cwd=cwd)!=row.get('execution_sha',row['source_sha']):raise ValueError('worktree_head_drift:'+lane)
        for file,expected_hash in row.get('composed_file_hashes',row.get('file_hashes',{})).items():
            if hashlib.sha256((cwd/file).read_bytes()).hexdigest()!=expected_hash:
                raise ValueError('frozen_source_file_drift:'+lane+':'+file)
        # Git's default abbreviated index IDs vary with repository object count.
        # Full IDs make the exact same prepared tree hash identically in CI and
        # an isolated local checkout. Preserve every content/mode/path byte.
        diff_args=['git','diff','--binary','--full-index','--no-ext-diff','--no-textconv','--no-renames']
        diff=subprocess.check_output([*diff_args,'HEAD'],cwd=cwd)
        observed[lane]=hashlib.sha256(diff).hexdigest()
        expected_diff_hash=row.get('source_diff_sha256')
        if row.get('source_integrity_mode')=='declared_overlay_index':
            for patch_path in lane_patches(lane,row):
                if not patch_path.is_file():
                    raise ValueError('missing_declared_overlay:'+lane+':'+str(patch_path))
            unstaged=subprocess.check_output(diff_args,cwd=cwd)
            if unstaged:
                raise ValueError('unreviewed_lane_mutation:'+lane)
            staged=subprocess.check_output([*diff_args,'--cached','HEAD'],cwd=cwd)
            if diff!=staged:
                raise ValueError('lane_index_worktree_disagreement:'+lane)
            if expected_diff_hash is None or observed[lane]!=expected_diff_hash:
                raise ValueError('declared_overlay_diff_identity_mismatch:'+lane)
        elif expected_diff_hash is not None:
            if observed[lane]!=expected_diff_hash:
                raise ValueError('unreviewed_lane_mutation:'+lane)
        else:
            patch={'pump':'pump-accounting.patch','meteora':'meteora-checkpoint.patch','pons':'pons-cohort-capital.patch','ramses':'ramses-admission.patch'}.get(lane)
            expected=(ROOT/'certification/patches'/patch).read_bytes() if patch else b''
            if canonical_patch_bytes(diff)!=canonical_patch_bytes(expected):
                raise ValueError('unreviewed_lane_mutation:'+lane)
    return observed


def integration_integrity():
    """Bind executable supervisor inputs to the commit named in the evidence."""
    tracked=subprocess.check_output(['git','diff','--binary','HEAD','--','certification','.github/workflows'],cwd=ROOT)
    if tracked:raise ValueError('uncommitted_integration_source')
    extras=subprocess.check_output(['git','ls-files','--others','-z','--','certification','.github/workflows'],cwd=ROOT).decode().split('\0')
    for name in filter(None,extras):
        if Path(name).suffix in ('.py','.patch','.yml','.yaml','.json'):
            raise ValueError('untracked_integration_source:'+name)



def _resolve_conflict_markers(text,path):
    pattern=re.compile(r'(?ms)^<<<<<<< ours\n(.*?)^=======\n(.*?)^>>>>>>> theirs\n')
    blocks=0
    def choose(match):
        nonlocal blocks
        blocks+=1
        ours,theirs=match.group(1),match.group(2)
        if path=='meme_machine/pump_acceleration_paper.py':
            if 'continuation_eligible' in ours and 'policy_hash' in theirs:
                return ('    POLICY, STRATEGY_ID, ExitObservation, Qualification, '
                        'continuation_eligible,\n'
                        '    exit_decision, mode_max_hold_s, policy_hash,\n')
            if 'realized_quote_units+=' in ours and 'self.book.transition' in theirs:
                book='\n'.join(
                    line for line in theirs.splitlines()
                    if 'self.position.realized_quote_units=' not in line
                )+'\n'
                return book+ours
        if path=='tests/pump_acceleration_natural_prospective.py':
            if '_monitor_positions(' in theirs and 'partial_harvest_bps' in ours:
                return theirs
        raise ValueError('unreviewed_pump_overlay_conflict:'+path)
    resolved=pattern.sub(choose,text)
    if '<<<<<<< ' in resolved or '>>>>>>> ' in resolved or '\n=======\n' in resolved:
        raise ValueError('unresolved_pump_overlay_conflict:'+path)
    if not blocks:
        raise ValueError('expected_pump_overlay_conflict_missing:'+path)
    return resolved


def _port_pump_partial_accounting(work):
    accounting=work/'meme_machine/paper_accounting.py'
    text=accounting.read_text()
    old="""            elif action == 'mark':
                if p['status'] != 'open':
                    raise ValueError('invalid_paper_mark')
                p['mark'] = amount
            elif action == 'settled':
                if p['status'] != 'open':
                    raise ValueError('duplicate_or_invalid_paper_settlement')
                p.update(status='settled', realized=amount-p['basis'], proceeds=amount,
                         basis=0, mark=0, tokens=0, capital_at_risk=0)
"""
    new="""            elif action == 'mark':
                if p['status'] != 'open':
                    raise ValueError('invalid_paper_mark')
                p['mark'] = amount
            elif action == 'partial_harvest':
                if p['status'] != 'open' or not tokens or tokens >= p['tokens']:
                    raise ValueError('invalid_paper_partial_harvest')
                old_tokens=p['tokens'];old_basis=p['basis']
                basis_removed=old_basis*tokens//old_tokens
                if basis_removed <= 0:
                    raise ValueError('paper_partial_harvest_basis_zero')
                p.update(
                    basis=old_basis-basis_removed,
                    mark=old_basis-basis_removed,
                    tokens=old_tokens-tokens,
                    realized=p['realized']+amount-basis_removed,
                    capital_at_risk=old_basis-basis_removed,
                )
            elif action == 'settled':
                if p['status'] != 'open':
                    raise ValueError('duplicate_or_invalid_paper_settlement')
                p.update(
                    status='settled',
                    realized=p['realized']+amount-p['basis'],
                    proceeds=amount,basis=0,mark=0,tokens=0,capital_at_risk=0,
                )
"""
    if text.count(old)!=1:
        raise ValueError('pump_accounting_transition_anchor')
    text=text.replace(old,new,1)
    old="""                elif action == 'settled':
                    if not old or old['status'] != 'open' or p['realized'] != p['proceeds']-old['basis']:
                        raise ValueError('paper_replay_settlement')
                    cash += p['proceeds']
                elif action != 'mark' or not old or old['status'] != 'open':
                    raise ValueError('paper_replay_transition')
"""
    new="""                elif action == 'partial_harvest':
                    if not old or old['status'] != 'open':
                        raise ValueError('paper_replay_partial_harvest')
                    sold=old['tokens']-p['tokens']
                    if sold <= 0 or sold >= old['tokens']:
                        raise ValueError('paper_replay_partial_harvest_tokens')
                    basis_removed=old['basis']*sold//old['tokens']
                    proceeds=(p['realized']-old['realized'])+basis_removed
                    if (basis_removed <= 0
                            or p['basis'] != old['basis']-basis_removed
                            or p['capital_at_risk'] != p['basis']
                            or p['mark'] != p['basis']
                            or proceeds < 0):
                        raise ValueError('paper_replay_partial_harvest')
                    cash += proceeds
                elif action == 'settled':
                    if (not old or old['status'] != 'open'
                            or p['realized'] != old['realized']+p['proceeds']-old['basis']):
                        raise ValueError('paper_replay_settlement')
                    cash += p['proceeds']
                elif action != 'mark' or not old or old['status'] != 'open':
                    raise ValueError('paper_replay_transition')
"""
    if text.count(old)!=1:
        raise ValueError('pump_accounting_replay_anchor')
    accounting.write_text(text.replace(old,new,1))

    lifecycle=work/'meme_machine/pump_acceleration_paper.py'
    text=lifecycle.read_text()
    old='    def harvest(self, tokens_sold: int, executable_proceeds_quote_units: int, now: int):\n'
    new='    def harvest(self, tokens_sold: int, executable_proceeds_quote_units: int, now: int, *, evidence=None):\n'
    if text.count(old)!=1:
        raise ValueError('pump_harvest_signature_anchor')
    text=text.replace(old,new,1)
    old="""        if proceeds < 0:
            raise ValueError("invalid_partial_harvest")
        before_tokens=int(self.position.tokens)
"""
    new="""        if proceeds < 0:
            raise ValueError("invalid_partial_harvest")
        if self.book is not None:
            self.book.transition(
                self.lifecycle_id,"partial_harvest",int(now),
                amount=proceeds,tokens=tokens_sold,
                evidence=dict(execution=evidence),
            )
        before_tokens=int(self.position.tokens)
"""
    if text.count(old)!=1:
        raise ValueError('pump_harvest_book_anchor')
    lifecycle.write_text(text.replace(old,new,1))

    runner=work/'tests/pump_acceleration_natural_prospective.py'
    text=runner.read_text()
    lines=text.splitlines()
    frozen=[i for i,line in enumerate(lines) if line.startswith('FROZEN_POLICY_HASH=')]
    if len(frozen)!=1:
        raise ValueError('pump_frozen_policy_hash_anchor')
    lines[frozen[0]]='FROZEN_POLICY_HASH="825084f162efdc10ca4d1faad747902b858bb6e7b4441f7ff48bf089a182f28b"'
    text='\n'.join(lines)+'\n'
    anchor="""            mark=life.mark(proceeds,now,demand_score,confirmed,evidence=mark_evidence)
            age=now-int(row["opened"])
"""
    addition="""            mark=life.mark(proceeds,now,demand_score,confirmed,evidence=mark_evidence)
            if mark.get("partial_harvest_bps"):
                tokens_before=int(life.position.tokens)
                if tokens_before>1:
                    harvest_tokens=max(
                        1,tokens_before*int(mark["partial_harvest_bps"])//10_000)
                    harvest_tokens=min(tokens_before-1,harvest_tokens)
                    if life.position.surface=="pump.fun":
                        curve=pump.curve(snapshot["accounts"][0])
                        supply,_=pump.mint_info(snapshot["accounts"][1])
                        rates=pump.fees(snapshot["accounts"][2],curve,supply)
                        partial_raw,_=pump.sell(curve,harvest_tokens,rates)
                        harvest_proceeds=max(0,partial_raw-GAS)
                    else:
                        partial_quote=sell_quote(snapshot,harvest_tokens)
                        harvest_proceeds=max(0,partial_quote.output_amount-GAS)
                    harvest_evidence=dict(
                        snapshot=snapshot,tokens_sold=harvest_tokens,
                        net_proceeds=harvest_proceeds,network_cost=GAS)
                    harvest=life.harvest(
                        harvest_tokens,harvest_proceeds,now,
                        evidence=harvest_evidence)
                    report.setdefault("harvests",[]).append(dict(
                        lifecycle_id=life.lifecycle_id,mint=mint,mode=mode,
                        opened=row["opened"],observed_at=now,
                        return_bps=mark["return_bps"],**harvest))
            age=now-int(row["opened"])
"""
    if text.count(anchor)!=1:
        raise ValueError('pump_monitor_harvest_anchor')
    runner.write_text(text.replace(anchor,addition,1))

    tests=work/'tests/test_paper_accounting.py'
    text=tests.read_text()
    marker="\nif __name__=='__main__':unittest.main()\n"
    test="""    def test_partial_harvest_preserves_cash_basis_and_replay(self):
        self.book.reserve('r:p',600,10,{})
        self.book.transition('r:p','filled',12,amount=550,tokens=100)
        self.book.transition('r:p','mark',20,amount=700)
        self.book.transition('r:p','partial_harvest',21,amount=200,tokens=25)
        rec=self.book.reconcile()
        self.assertEqual(rec['cash'],650)
        self.assertEqual(rec['basis'],413)
        self.assertEqual(rec['realized'],63)
        self.assertEqual(self.book.replay()['cash'],650)
        self.book.transition('r:p','settled',30,amount=500)
        rec=self.book.reconcile()
        self.assertEqual(rec['cash'],1150)
        self.assertEqual(rec['realized'],150)
        self.assertEqual(self.book.replay()['cash'],1150)

"""
    if marker not in text:
        raise ValueError('pump_accounting_test_anchor')
    tests.write_text(text.replace(marker,'\n'+test+marker,1))


def _apply_pump_profit_protection_accounting(work,patch_path):
    merged=subprocess.run(
        ['git','apply','--3way','--index',str(patch_path)],cwd=work,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
    )
    if merged.returncode==0:
        raise ValueError('pump_profit_protection_expected_rebase_not_needed')
    unmerged=git('diff','--name-only','--diff-filter=U',cwd=work).splitlines()
    expected={
        'meme_machine/pump_acceleration_paper.py',
        'tests/pump_acceleration_natural_prospective.py',
    }
    if set(unmerged)!=expected:
        raise ValueError('unexpected_pump_overlay_conflicts:'+','.join(sorted(unmerged)))
    for name in sorted(expected):
        target=work/name
        target.write_text(_resolve_conflict_markers(target.read_text(),name))
    _port_pump_partial_accounting(work)
    subprocess.run(['git','add','--all'],cwd=work,check=True)
    if git('diff','--name-only','--diff-filter=U',cwd=work):
        raise ValueError('unresolved_pump_profit_protection_overlay')
    subprocess.run(['git','diff','--check','--cached'],cwd=work,check=True)


def _resolve_meteora_checkpoint_conflicts(text):
    pattern=re.compile(r'(?ms)^<<<<<<< ours\n(.*?)^=======\n(.*?)^>>>>>>> theirs\n')
    count=0
    def choose(match):
        nonlocal count
        count+=1
        ours,theirs=match.group(1),match.group(2)
        if '_eligible_exit_reasons' in ours and '_position_lifecycle' in theirs:
            prefix=ours[:ours.index('def _lifecycle(')]
            return prefix+theirs
        if 'collapse_streaks' in ours and "book.append(identity,'mark'" in theirs:
            return """        if book is not None:
            book.append(identity,'mark',dict(
                tape=asdict(tape),position_hash=digest(position),mark=mark))
        observed_seconds=max(
            duration,
            max(0,int(terminal.get("time",0))-int(current.get("time",0))))
        elapsed+=observed_seconds;tapes.append(tape)
        for reason in collapse_streaks:
            collapse_streaks[reason]=(
                collapse_streaks[reason]+1 if reason in raw_reasons else 0
            )
        eligible_reasons=_eligible_exit_reasons(
            raw_reasons,elapsed_seconds=elapsed,
            collapse_streaks=collapse_streaks,policy=policy,
        )
        segments.append(dict(
            elapsed_seconds=elapsed,lineage=tape.lineage,
            swaps=len(tape.events),recent=recent,mark=mark,
            dynamic_fee_uplift=uplift,
            raw_exit_reasons=raw_reasons,
            collapse_streaks=dict(collapse_streaks),
            exit_reasons=eligible_reasons,
            evidence_recovery_attempts=recoveries,
        ))
        current=terminal
        if eligible_reasons:
            exit_reason=eligible_reasons[0];break
    _stage(address,"unwind",lifecycle_id=identity)
"""
        raise ValueError('unreviewed_meteora_checkpoint_conflict')
    resolved=pattern.sub(choose,text)
    if count!=2 or '<<<<<<< ' in resolved or '>>>>>>> ' in resolved:
        raise ValueError('meteora_checkpoint_conflict_shape')
    return resolved


def _apply_meteora_core_hold_checkpoint(work,patch_path):
    merged=subprocess.run(
        ['git','apply','--3way','--index',str(patch_path)],cwd=work,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
    )
    if merged.returncode==0:
        return
    unmerged=git('diff','--name-only','--diff-filter=U',cwd=work).splitlines()
    if unmerged!=['tests/solana_dlmm_independent_v1.py']:
        raise ValueError('unexpected_meteora_checkpoint_conflicts:'+','.join(unmerged))
    target=work/unmerged[0]
    target.write_text(_resolve_meteora_checkpoint_conflicts(target.read_text()))
    subprocess.run(['git','add','--all'],cwd=work,check=True)
    if git('diff','--name-only','--diff-filter=U',cwd=work):
        raise ValueError('unresolved_meteora_checkpoint_overlay')
    subprocess.run(['git','diff','--check','--cached'],cwd=work,check=True)


def _apply_three_way_or_diagnose(work,patch_path,lane):
    merged=subprocess.run(
        ['git','apply','--3way','--index',str(patch_path)],cwd=work,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
    )
    if merged.returncode==0:
        return
    print(merged.stdout,flush=True)
    unmerged=git('diff','--name-only','--diff-filter=U',cwd=work).splitlines()
    for name in unmerged:
        body=(work/name).read_text()
        lines=body.splitlines()
        for index,line in enumerate(lines):
            if line.startswith('<<<<<<< '):
                lo=max(0,index-15);hi=min(len(lines),index+90)
                print('--- '+lane.upper()+' CONFLICT '+name+' ---',flush=True)
                print('\n'.join(
                    f'{number+1}: {lines[number]}' for number in range(lo,hi)
                ),flush=True)
    raise subprocess.CalledProcessError(
        merged.returncode,merged.args,output=merged.stdout)


def prepare(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=False)
    spec=manifest()
    for lane,row in spec['lanes'].items():
        work=destination/lane
        execution=row.get('execution_sha',row['source_sha'])
        subprocess.run(['git','fetch','origin',execution],cwd=ROOT,check=True)
        subprocess.run(['git','worktree','add','--detach',str(work),execution],cwd=ROOT,check=True)
        for file,expected in row['file_hashes'].items():
            if hashlib.sha256((work/file).read_bytes()).hexdigest()!=expected:raise ValueError('source_hash_mismatch:'+lane+':'+file)
        for patch_path in lane_patches(lane,row):
            strict=subprocess.run(
                ['git','apply','--check',str(patch_path)],cwd=work,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
            )
            if strict.returncode==0:
                subprocess.run(['git','apply','--index',str(patch_path)],cwd=work,check=True)
                continue
            if lane=='pump' and patch_path.name=='pump-accounting.patch':
                _apply_pump_profit_protection_accounting(work,patch_path)
                continue
            if lane=='meteora' and patch_path.name=='meteora-checkpoint.patch':
                _apply_meteora_core_hold_checkpoint(work,patch_path)
                continue
            _apply_three_way_or_diagnose(work,patch_path,lane)
            continue
    atomic(destination/'manifest.json',spec)
    return destination


def verify(worktrees,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    rows={}
    source_hashes=source_integrity(worktrees)
    for lane in LANES:
        cwd=Path(worktrees)/lane
        command=[sys.executable,'-m','unittest','discover']+(['-s','robinhood_tests'] if lane in ('pons','ramses') else [])+['-v']
        commands=[command]
        if lane in ('pump','meteora'):commands.append([sys.executable,'-m','tests.resource_check'])
        if lane=='meteora':commands.append([sys.executable,'-m','tests.dlmm_resource_check'])
        rows[lane]=[]
        for index,cmd in enumerate(commands):
            started=time.time();log=output/f'{lane}-gate-{index}.log'
            # Collect through a pipe, then durably write the complete child transcript.
            # A zero return code without the full unittest footer still fails.
            r=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            log.write_bytes(r.stdout)
            complete=index!=0 or ('\nRan ' in log.read_text() and '\nOK' in log.read_text())
            rows[lane].append(dict(command=cmd,exit_code=r.returncode,summary_complete=complete,started_at=started,ended_at=time.time(),log=log.name,sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    # Tests may change a worktree; a pre-test check alone cannot certify the
    # source handed to the subsequent paper worker.
    if source_integrity(worktrees)!=source_hashes:raise ValueError('source_changed_during_verification')
    result=dict(passed=all(x['exit_code']==0 and x['summary_complete'] for lane in rows.values() for x in lane),lanes=rows,
                source_manifest_hash=digest(manifest()),integration_sha=git('rev-parse','HEAD'),implementation_hash=implementation_hash(),source_diff_hashes=source_hashes)
    atomic(output/'deterministic.json',result)
    return result


def lane_environment(lane,source,run,run_id=None,phase=None):
    env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GITHUB_','GH_')) and not any(x in k.upper() for x in ('TOKEN','SECRET','PRIVATE_KEY'))}
    for key in source['rpc_configuration_variables']:
        if os.environ.get(key):env[key]=os.environ[key]
    if lane=='ramses':
        # Optional existing authorized inputs; strategy code still authenticates.
        for key in ('MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON','MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON'):
            if key in os.environ:env[key]=os.environ[key]
    env.update(PYTHONPATH=str(ROOT),PYTHONUNBUFFERED='1',MM_CERT_SOURCE_SHA=source['source_sha'],
               MM_CERT_INTEGRATION_SHA=git('rev-parse','HEAD'),
               MM_CERT_GOVERNOR_DB=str(run/'shared-provider.sqlite'),
               MM_CERTIFICATION_RUN_ID=run_id or run.name,MM_CERTIFICATION_LANE=lane,
               MM_CERTIFICATION_PHASE=str(phase or 'unknown'))
    if lane in ('pump','meteora'):
        env['MM_SOLANA_EVIDENCE_BROKER_DB']=str(run/'shared-solana-evidence.sqlite')
        env['MM_SOLANA_EVIDENCE_PLANE_DB']=str(run/'solana-evidence-plane.sqlite')
    else:env.update(MM_CERTIFICATION_PROVIDER_DB=str(run/'shared-robinhood-admission.sqlite'),MM_CERTIFICATION_LANE=lane,
                    MM_CERTIFICATION_RPC_CACHE_DB=str(run/'shared-robinhood-evidence.sqlite'),
                    MM_CERTIFICATION_RPC_CAPABILITIES=str(run/'rpc-capabilities.json'))
    return env


def observe_checkpoint_report(lane,row,status,process_code):
    # Once the process has returned, the copied native terminal report is final.
    # A stale progress snapshot must not erase its settlement/accounting evidence
    # while another lane is still draining.
    if status.get('report') is not None and (process_code is None or 'exit_code' not in row):
        row.update(summarize(lane,status['report']))


def reconcile_stopped_lane(lane,worktrees):
    proof=subprocess.run([sys.executable,str(ROOT/'certification/terminal_reconciliation.py'),
        '--lane',lane,'--root',str((Path(worktrees)/lane).resolve())],
        capture_output=True,text=True,timeout=45)
    receipt=json.loads(proof.stdout)
    if proof.returncode!=0:receipt['verified']=False
    return receipt


def finish_lanes(processes,files,rows,terminal_times,journal,run,worktrees=None):
    """Stop/reap every child before auditing any lane's possibly damaged evidence."""
    stopped=set()
    # SIGINT lets the worker's BaseException/finally path seal its raw archive.
    # This is still an interrupted lifecycle, never a normal policy exit.
    for lane,(proc,launched) in processes.items():
        if proc.poll() is None:
            stopped.add(lane)
            try:os.killpg(proc.pid,signal.SIGINT)
            except ProcessLookupError:pass
    deadline=time.monotonic()+10
    for lane,(proc,launched) in processes.items():
        if lane in stopped:
            try:proc.wait(timeout=max(.01,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            ended=time.monotonic();terminal_times[lane]=ended
            rows[lane].update(unexpected_exit=True,exit_code=proc.returncode,health='terminated',
                ended_at=time.time(),continuous_uptime_seconds=ended-launched,
                shutdown_positions='explicitly_unresolved',accounting_reconciled=False)
        files[lane].close()
    # One corrupt/truncated archive must fail that lane's control, without
    # suppressing the other three audits or the aggregate terminal result.
    for lane,(proc,launched) in processes.items():
        row=rows[lane]
        if worktrees is not None:
            try:
                receipt=reconcile_stopped_lane(lane,worktrees)
                row['terminal_reconciliation']=receipt
                journal.append(lane,'terminal-reconciliation','native_accounting_replay',receipt)
                if receipt.get('verified') is True:
                    row['accounting_reconciled']=True
                    row['open_positions']=receipt['open_positions']
                    key='cohort_accounting' if lane=='pons' else 'native_accounting'
                    row[key]=receipt['accounting']
                    if 'accounting_replay' in receipt:row['accounting_replay']=receipt['accounting_replay']
                    if receipt.get('durable_handoff') is True:
                        row['durable_handoff']=True
                        row['continuation_state']=receipt.get('continuation_state')
                    if lane in stopped:row['shutdown_positions']='durable_native_state_reconciled'
                else:row['accounting_reconciled']=False
            except Exception as exc:
                row['terminal_reconciliation']=dict(verified=False,error_type=type(exc).__name__)
                row['accounting_reconciled']=False
        if lane in stopped:
            try:journal.append(lane,'supervisor_stop','forced_process_stop',dict(exit_code=proc.returncode))
            except Exception as exc:row['shutdown_journal_error']=type(exc).__name__
        try:
            audit=audit_telemetry(run/lane,lane,row['policy_hash'],require_returned=False)
            row['telemetry_audit']=audit
            row['gates'].update(telemetry_complete=True,paper_only=audit['read_only'])
            row['gates'].setdefault('policy_unchanged',True)
        except Exception as exc:
            row['telemetry_audit']=dict(verified=False,error_type=type(exc).__name__)
            row['gates']['telemetry_complete']=False
        if row.get('shutdown_journal_error'):row['gates']['telemetry_complete']=False
        row['gates']['accounting_reconciled']=row.get('accounting_reconciled') is True
    return bool(stopped)


def launch(worktrees,output,seconds,phase,gate_file,smoke_result=None):
    if phase=='sustained' and seconds<14400:raise ValueError('four_hour_minimum')
    if phase=='hourly' and seconds!=3600:raise ValueError('one_hour_window_required')
    integration_integrity()
    gate=json.loads(Path(gate_file).read_text())
    if not gate.get('passed') or gate.get('source_manifest_hash')!=digest(manifest()):raise ValueError('exact_source_deterministic_gate_required')
    if gate.get('integration_sha')!=git('rev-parse','HEAD'):raise ValueError('integration_sha_gate_mismatch')
    if gate.get('implementation_hash')!=implementation_hash():raise ValueError('implementation_gate_mismatch')
    if gate.get('source_diff_hashes')!=source_integrity(worktrees):raise ValueError('source_gate_mismatch')
    run=Path(output).resolve();run.mkdir(parents=True,exist_ok=False)
    spec=manifest();run_id=str(uuid.uuid4())
    capabilities=Path(gate_file).parent/'rpc-capabilities.json'
    if capabilities.exists():atomic(run/'rpc-capabilities.json',json.loads(capabilities.read_text()))
    runtime_manifest=dict(**spec,integration_sha=git('rev-parse','HEAD'),run_id=run_id)
    if 'meteora' in spec.get('lanes',{}):
        overlay=ROOT/'certification/patches/meteora-checkpoint.patch'
        if not overlay.is_file():
            raise ValueError('meteora_operational_overlay_missing')
        runtime_manifest['operational_overlay_sha256']=hashlib.sha256(overlay.read_bytes()).hexdigest()
    atomic(run/'manifest.json',runtime_manifest)
    unresolved=historical_exposure()
    if unresolved:
        result=dict(run_id=run_id,phase=phase,status='BLOCKED',
            blockers=['historical_unresolved_exposure:'+row['lane'] for row in unresolved],
            historical_exposure=unresolved,lanes={},elapsed_seconds=0)
        provider_efficiency(result);result['certification']=evaluate(result)
        atomic(run/'result.json',result);dashboard(result,run/'status.html')
        return result
    if phase in ('sustained','hourly'):
        blockers=sustained_readiness(smoke_result,manifest_hash=digest(spec),
            implementation_hash=implementation_hash(),integration_sha=git('rev-parse','HEAD'))
        if blockers:
            result=dict(run_id=run_id,phase=phase,status='BLOCKED',blockers=blockers,lanes={},elapsed_seconds=0)
            provider_efficiency(result);result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html')
            return result
    for lane,row in spec['lanes'].items():
        if git('rev-parse','HEAD',cwd=Path(worktrees)/lane)!=row.get('execution_sha',row['source_sha']):raise ValueError('worktree_head_drift:'+lane)
        for f,h in row.get('composed_file_hashes',row['file_hashes']).items():
            if hashlib.sha256((Path(worktrees)/lane/f).read_bytes()).hexdigest()!=h:raise ValueError('policy_or_config_drift:'+lane)
    required=('MM_SOLANA_READ_RPC_URL','MM_ROBINHOOD_READ_RPC_URL')
    missing=[k for k in required if not os.environ.get(k)]
    if missing:
        result=dict(run_id=run_id,phase=phase,status='BLOCKED',blockers=['missing_authorized_runtime_variable:'+k for k in missing],lanes={},elapsed_seconds=0)
        provider_efficiency(result);result['certification']=evaluate(result);atomic(run/'result.json',result);dashboard(result,run/'status.html');return result
    provider_config={}
    for lane,row in spec['lanes'].items():
        provider_config[lane]={k:dict(configured=bool(os.environ.get(k)),identity=(hashlib.sha256(os.environ[k].encode()).hexdigest()[:16] if os.environ.get(k) else None)) for k in row['rpc_configuration_variables']}
    atomic(run/'provider-identities.json',provider_config)
    journal=Journal(run/'supervisor.sqlite');governor=Governor(run/'shared-provider.sqlite')
    pressure=PressureView(run/'shared-robinhood-admission.sqlite')
    solana_reuse=SolanaReuseView(run/'shared-solana-evidence.sqlite')
    reuse=ReuseView(run/'shared-robinhood-evidence.sqlite')
    started=time.monotonic();start_wall=time.time();processes={};files={};rows={};interrupted=False;terminal_times={}
    common_start=started
    last_console=0;last_sample=0;max_broker_active=0;broker_terminal=None;supervisor_error=None
    lane_roots=[str((Path(worktrees)/lane).resolve()) for lane in LANES]
    if len(set(lane_roots))!=len(LANES):raise ValueError('lane_state_roots_not_isolated')
    from certification.evidence_supervisor import EvidenceProcess
    from meme_machine.solana_evidence_health import HealthWatch
    evidence_watches={lane:HealthWatch(time.monotonic()) for lane in ('pump','meteora')}
    evidence=EvidenceProcess(run,Path(worktrees)/'pump',lane_environment('pump',spec['lanes']['pump'],run,run_id,phase))
    try:
        evidence.start()
        for lane,row in spec['lanes'].items():
            folder=run/lane;folder.mkdir()
            out=(folder/'process.log').open('wb');files[lane]=out
            cmd=[sys.executable,'-m','certification.worker','--lane',lane,'--output',str(folder),'--policy-hash',row['policy_hash'],'--seconds',str(seconds),'--campaign']
            proc=subprocess.Popen(cmd,cwd=Path(worktrees)/lane,env=lane_environment(lane,row,run,run_id,phase),stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
            launched=time.monotonic();processes[lane]=(proc,launched)
            rows[lane]=dict(pid=proc.pid,strategy_version=row['strategy_version'],policy_hash=row['policy_hash'],process_restarts=0,health='starting',natural_settled=0,forced_settled=0,
                max_no_activity_seconds=0,gates=dict(responsive=True,state_isolated=True))
            journal.append(lane,'launch','process_launch',dict(pid=proc.pid,command=cmd,source_sha=row['source_sha'],launched_monotonic=launched))
        # Drain lets normal policy-defined exits finish. It is never counted as
        # a replacement for an interrupted observation window.
        common_start=max(start for _proc,start in processes.values())
        hard_deadline=common_start+seconds+3300
        while True:
            evidence_health=evidence.check()
            now=time.monotonic();alive=False
            for lane,(proc,launched) in processes.items():
                row=rows[lane];code=proc.poll();path=run/lane/'status.json';status={}
                if path.exists():
                    try:status=json.loads(path.read_text())
                    except (ValueError,OSError):status={}
                    if status:
                        if status.get('pid')!=proc.pid or status.get('lane')!=lane:
                            row['gates']['state_isolated']=False
                        nonce=status.get('process_nonce')
                        if row.get('process_nonce') is not None and row['process_nonce']!=nonce:
                            row['process_restarts']+=1
                        row['process_nonce']=nonce
                    row.update({k:status[k] for k in ('phase','estimated_alchemy','provider_requests','method_counts','errors','local_admission_errors','provider_method_errors','provider_http_status_errors','provider_rpc_error_codes','rpc_latency_seconds','telemetry_archive_seconds','telemetry_cost','runtime_resources') if k in status})
                    progress=status.get('last_progress_monotonic')
                    row['progress_age_seconds']=None if progress is None else now-progress
                    if 'exit_code' not in row:row['health']='responsive' if progress is not None and now-progress<300 else 'progress_stalled'
                    observe_checkpoint_report(lane,row,status,code)
                    if status.get('policy_hash')!=row['policy_hash']:row['gates']['policy_unchanged']=False
                activity_file=run/lane/'activity.json'
                if activity_file.exists() and code is None:
                    try:activity=json.loads(activity_file.read_text())
                    except (ValueError,OSError):activity={}
                    if activity.get('pid')==proc.pid and activity.get('lane')==lane:
                        at=activity.get('at_monotonic',0)
                        if isinstance(at,(int,float)) and 0<=now-at<300:
                            row['health']='responsive';row['transport_activity_age_seconds']=now-at
                        if isinstance(at,(int,float)) and at>(status.get('last_progress_monotonic') or 0):
                            row.update({k:activity[k] for k in ('provider_requests','method_counts','estimated_alchemy','errors','local_admission_errors','provider_method_errors','provider_http_status_errors','provider_rpc_error_codes','provider_session_count') if k in activity})
                if code is None:
                    alive=True;row['continuous_uptime_seconds']=now-launched
                    last=status.get('last_progress_monotonic') or launched
                    if activity_file.exists():
                        try:
                            heartbeat=json.loads(activity_file.read_text())
                            if heartbeat.get('pid')==proc.pid and heartbeat.get('lane')==lane:
                                last=max(last,heartbeat.get('at_monotonic',launched))
                        except (ValueError,OSError):pass
                    idle=max(0,now-last)
                    row['max_no_activity_seconds']=max(row['max_no_activity_seconds'],idle)
                    if idle>300:row['gates']['responsive']=False
                elif 'exit_code' not in row:
                    reported=status.get('terminal_monotonic')
                    ended=reported if isinstance(reported,(int,float)) and launched<=reported<=now else now
                    terminal_times[lane]=ended
                    row.update(exit_code=code,ended_at=time.time(),continuous_uptime_seconds=ended-launched,unexpected_exit=code!=0 or ended-common_start<seconds,health='exited')
                    report=Path(worktrees)/lane/REPORTS[lane]
                    if report.exists():
                        raw=report.read_bytes();(run/lane/REPORTS[lane]).write_bytes(raw)
                        try:
                            native=json.loads(raw);row.update(summarize(lane,native))
                            if lane=='pons':
                                from certification.terminal_receipts import emit_pons
                                emit_pons(native)
                        except ValueError:row['report_parse_error']=True
                    if lane in evidence_watches and evidence_watches[lane].failure:
                        row['infrastructure_failure']=evidence_watches[lane].failure
                    if lane=='pump' and phase=='smoke':
                        from certification.solana_lifecycle import pump_flat_completion
                        if pump_flat_completion(row):
                            row.update(unexpected_exit=False,health='flat_after_discovery')
                    if row.get('infrastructure_failure'):
                        row['gates']['responsive']=False;row['health']='evidence_failed'
                    journal.append(lane,'exit','process_exit',dict(exit_code=code,observed_monotonic=now,unexpected=row['unexpected_exit']))
                row['open_positions_unknown']=row.get('open_positions') is None
                if lane in evidence_watches and code is None and isinstance(evidence_health,dict):
                    current=evidence_health.get('lanes',{}).get(lane)
                    if isinstance(current,dict):
                        watch=evidence_watches[lane];watch.observe(current,now)
                        row['evidence_service_health']=watch.snapshot()
                        if watch.failure:
                            row['infrastructure_failure']=watch.failure
                            row['gates']['responsive']=False;row['health']='evidence_failed'
                row['process_health']=row['health']
                row['pipeline_health']=pipeline_health(row,time.time())
                if code is None and row['health']=='responsive' and row['pipeline_health']['state']=='stalled':
                    row['health']='responsive_but_strategy_stalled'
            result=dict(run_id=run_id,phase=phase,status='RUNNING' if alive else 'FINISHED',started_at=start_wall,observed_at=time.time(),elapsed_seconds=now-started,continuous_overlap_seconds=max(0,min(terminal_times.values(),default=now)-common_start),lanes=rows,shared_provider=dict(solana=governor.status(),robinhood=pressure.snapshot(),robinhood_reuse=reuse.snapshot(),solana_reuse=solana_reuse.snapshot()),source_manifest_hash=digest(spec))
            if now-last_sample>=30:
                broker=broker_snapshot(run/'shared-solana-evidence.sqlite')
                max_broker_active=max(max_broker_active,(broker or {}).get('active',0))
                journal.append('supervisor','resource-sample:'+str(time.monotonic_ns()),'resource_sample',
                    dict(broker=broker,providers=result['shared_provider'],health={k:r['health'] for k,r in rows.items()},
                        runtime_resources={k:r.get('runtime_resources') for k,r in rows.items()},
                        telemetry_cost={k:r.get('telemetry_cost') for k,r in rows.items()}))
                last_sample=now
            provider_efficiency(result);result['certification']=evaluate(result)
            from meme_machine.durable_publication import publish_report
            publish_report(run/'result.json',result,asynchronous=True)
            result['dashboard_publication']=publish_dashboard(result,run/'status.html')
            if now-last_console>=60:
                print(canonical(dict(run_id=run_id,elapsed_seconds=now-started,lanes={k:{f:v for f,v in r.items() if f in ('health','phase','continuous_uptime_seconds','provider_requests','natural_settled','forced_settled','unexpected_exit')} for k,r in rows.items()})),flush=True)
                last_console=now
                if os.environ.get('GITHUB_STEP_SUMMARY'):
                    summary=['| Lane | Health | Uptime seconds | Requests | Natural / forced settled |','|---|---|---:|---:|---:|']
                    for k,r in rows.items():summary.append(f"| {k} | {r.get('health')} | {r.get('continuous_uptime_seconds',0):.1f} | {r.get('provider_requests','unknown')} | {r.get('natural_settled',0)} / {r.get('forced_settled',0)} |")
                    Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('\n'.join(summary)+'\n\nCertification is not PASS while required controls remain unproven.\n')
            if not alive:break
            if now>=hard_deadline:
                result['shutdown_reason']='bounded_drain_deadline';interrupted=True;break
            time.sleep(2)
    except BaseException as exc:
        interrupted=True;supervisor_error=dict(error_type=type(exc).__name__)
        raise
    finally:
        interrupted=finish_lanes(processes,files,rows,terminal_times,journal,run,worktrees) or interrupted
        for lane,watch in evidence_watches.items():
            if watch.failure:
                rows[lane]['infrastructure_failure']=watch.failure
                rows[lane]['gates']['responsive']=False
        evidence.close()
        broker_terminal=record_unfinished_broker_jobs(run/'shared-solana-evidence.sqlite',journal,time.time())
        try:source_unchanged=source_integrity(worktrees)==gate['source_diff_hashes']
        except (ValueError,OSError,subprocess.CalledProcessError):source_unchanged=False
        for row in rows.values():
            row['gates']['freshness_finality_unchanged']=source_unchanged
            if not source_unchanged:row['gates']['policy_unchanged']=False
        result=dict(run_id=run_id,phase=phase,status='FAILED' if interrupted else 'FINISHED',started_at=start_wall,ended_at=time.time(),elapsed_seconds=time.monotonic()-started,continuous_overlap_seconds=max(0,min(terminal_times.values(),default=time.monotonic())-common_start),source_manifest_hash=digest(spec),lanes=rows,shared_provider=dict(solana=governor.status(),robinhood=pressure.snapshot(),robinhood_reuse=reuse.snapshot(),solana_reuse=solana_reuse.snapshot()))
        result.update(supervisor_error=supervisor_error,integration_sha=git('rev-parse','HEAD'),implementation_hash=implementation_hash(),
            maximum_sampled_active_broker_jobs=max_broker_active,broker_shutdown_terminals=broker_terminal,
            source_diff_hashes=gate['source_diff_hashes'])
        if phase=='smoke':result['smoke_engineering']=smoke_engineering(result)
        provider_efficiency(result);result['certification']=evaluate(result)
        if phase=='hourly':result['hourly_engineering']=hourly_engineering(result)
        provider_efficiency(result);atomic(run/'result.json',result);journal.close()
        publish_dashboard(result,run/'status.html')
        from certification.analysis import report
        report(run)
    return result


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--worktrees',required=True)
    p=sub.add_parser('verify');p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('run');p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);p.add_argument('--gate',required=True)
    p.add_argument('--seconds',type=int,default=600);p.add_argument('--phase',choices=['smoke','sustained','hourly'],default='smoke')
    p.add_argument('--smoke-result')
    args=parser.parse_args()
    if args.command=='prepare':print(prepare(args.worktrees));return
    if args.command=='verify':
        r=verify(args.worktrees,args.output);print(canonical(r));raise SystemExit(0 if r['passed'] else 1)
    r=launch(args.worktrees,args.output,args.seconds,args.phase,args.gate,args.smoke_result)
    print(canonical(r))
    if args.phase=='smoke':success=r.get('smoke_engineering',{}).get('status')=='PASS'
    elif args.phase=='hourly':success=r.get('hourly_engineering',{}).get('status')=='PASS'
    else:success=r['certification']['status']=='PASS'
    raise SystemExit(0 if success else 1)

if __name__=='__main__':main()
