"""Offline source-validated Pons lifecycle, authority and bound map."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

BASE='meme_machine/lanes/pons/'
FILES=dict(
    cohort=BASE+'pons_selective_cohort.py',acquisition=BASE+'pons_selective_acquisition.py',
    current=BASE+'pons_selective_continuation.py',window=BASE+'pons_current_window.py',
    current_history=BASE+'pons_current_history.py',paper=BASE+'pons_selective_paper.py',
    recovery=BASE+'pons_selective_recovery.py',capital=BASE+'pons_selective_capital.py',
    ledger=BASE+'pons_selective_ledger.py',survivor=BASE+'pons_survivor_runtime.py',
    survivor_policy=BASE+'pons_postgrad_survivor.py',history=BASE+'pons_history.py',
    v4=BASE+'pons_selective_v4.py',quotes=BASE+'pons_quotes.py',graduation=BASE+'pons_natural_paper.py',
    protocol=BASE+'pons.py',natural=BASE+'pons_natural_observation.py',
    legacy=BASE+'continuation_robinhood.py',legacy_cohort=BASE+'continuation_robinhood_cohort.py',
    legacy_sample=BASE+'continuation_robinhood_sample.py',
    breakout_sample=BASE+'pons_breakout_sample.py',relative_sample=BASE+'pons_relative_sample.py',
    provider=BASE+'provider_topology.py',admission=BASE+'provider_admission.py',
    immutable=BASE+'immutable_rpc.py',attempts=BASE+'pons_attempts.py',feed=BASE+'sequencer_feed.py',
    authority='meme_machine/runtime/robinhood/provider_authority.py',
    plane='meme_machine/runtime/robinhood/plane.py',broker='meme_machine/runtime/robinhood/pons.py',
    generic_history='meme_machine/runtime/survivor_history.py',
    book='meme_machine/runtime/survivor_paper_book.py',sleeve='meme_machine/runtime/sleeve_reservations.py',
    sleeve_policy='meme_machine/runtime/directional_sleeve.py',
    commit='meme_machine/runtime/survivor_commit.py',risk='meme_machine/runtime/survivor_risk.py',
    continuation='meme_machine/runtime/directional_continuation.py',
    execution='meme_machine/runtime/execution_capacity.py',entrypoint='meme_machine/operational/lane.py')

# Each tuple is a lifecycle stage, its actual authority, and source symbols.
CURRENT=[
    ('discovery','All-address CurveBuy/CurveSell public log ranges; sequencer supplies only block clock.',
     ['cohort.run','cohort._start_observation','cohort._poll','cohort._discovery_curve_events','feed.SequencerBlockClock.wait_for_range_after']),
    ('candidate_retention','Independent curve identity and fenced generation; cash does not gate observation.',
     ['broker.Broker.enqueue','broker.Broker.pop','plane.Plane.observe','plane.Plane.claim','plane.Plane.recover']),
    ('market_observation','Public nominations never supply authoritative strategy fields.',
     ['cohort._current_curve_events','window.canonical_window']),
    ('evidence_acquisition','Canonical chain 4663, exact compiled CREATE2 identity, receipt/header and current ABI state.',
     ['acquisition.evaluate_candidate','natural._authenticate_candidate','protocol.authenticate_curve','acquisition._trajectory','acquisition._authenticate_window']),
    ('qualification','Frozen progress/age/trajectory/demand/concentration/creator/cost vector; realized-equity target.',
     ['current.qualification_vector','current.trajectory_metrics','current.demand_metrics','current.entry_size','current.roundtrip_loss_bps']),
    ('durable_decision','Full normalized evidence and qualification commit before any funding disposition.',
     ['broker.Broker.finish','plane.Plane.finish','attempts.Attempts.record','broker.Broker.committed']),
    ('funding_reservation','Cash/capacity/same-asset conflicts occur after qualification; native reservation is idempotent.',
     ['paper.run_lifecycle','capital.CohortCapital.reserve','ledger.SelectivePaper.reserve','sleeve.SleeveReservations.reserve']),
    ('entry','Two-second modeled delay, fresh signal/breadth/state/quote, generation fence and canonical delta.',
     ['paper._run_lifecycle','paper._refresh_entry_persistence_signal','paper._confirm_entry_delta','paper._validate_final_entry','ledger.SelectivePaper.advance']),
    ('monitoring','Position work priority; fresh executable marks and complete safety flow; history accumulates approved add window.',
     ['paper._curve_logs','paper._read_curve_logs','paper._refresh_curve_signal','current_history.CurrentHistory.remember','current_history.CurrentHistory.facts','quotes.v4_quote','quotes.PinnedV4Reads.call','admission.position_work']),
    ('partial_realization','At +18% sell 25%; native ledger realizes proceeds without rebasing original risk.',
     ['current.pregraduation_action','current.runner_action','ledger.SelectivePaper.advance','capital.CohortCapital.observe']),
    ('ordinary_trail_adverse_flow','12% runner drawdown before 2x; 1.20x adverse sell/buy and existing confirmations/safety.',
     ['current.pregraduation_action','current.pregraduation_soft_deterioration','current.runner_action','current.runner_soft_deterioration']),
    ('right_tail','At >=2x, floor on return is 60% of peak profit, preserving 40% peak-profit giveback.',
     ['current.pregraduation_action','current.runner_action','continuation.reference_return']),
    ('staged_add','One fresh full requalification after 2x/harvest/900s/within15%HWM; existing cash/capacity/exposure ceilings.',
     ['paper._ongoing_scale_evidence','current.ongoing_scale_requalification','paper._attempt_current_scale','continuation.scale_budget','sleeve.SleeveReservations.reserve_scale']),
    ('bridge','Same native position/basis/HWM; existing strong-winner gates; deadline original open +36h.',
     ['paper._bridge_action','continuation.bridge_state','recovery.LifecycleState.checkpoint']),
    ('graduation_continuation','V2 factory graduation and registered/initialized V4 native pool; five-to45second existing continuation gates.',
     ['current.post_graduation_vector','v4.collect_v4_activity','protocol.prove_v4_lineage']),
    ('exit_settlement','Authenticated executable exit or durable pending intent; exact realized P&L and native verification before release.',
     ['paper._delayed_exit','paper._complete_pending_v4_exit','ledger.SelectivePaper.advance','ledger.SelectivePaper.accounting','capital.CohortCapital.settle']),
    ('restart','Native reconciliation precedes discovery; original evidence/clock/controller/reservation retained; stale quotes reacquired.',
     ['recovery.LifecycleState.restore','recovery.resume_lifecycle','recovery.submit_existing_lifecycles','broker.save_cohort_checkpoint','current_history.CurrentHistory.get'])]

SURVIVOR=[
    ('discovery','Canonical Pons V2 factory PoolGraduated; independent seven-day bootstrap and hashed cursor.',
     ['survivor.Runtime.discover','survivor.Runtime._bootstrap_cursor','history.PonsHistory.retain_graduations','graduation._graduation_transition']),
    ('candidate_retention','All raw nominees commit with range watermark before bounded one-member authentication; no Current-state dependency.',
     ['history.PonsHistory.graduation_batch','history.PonsHistory.graduation_complete','generic_history.History.graduate']),
    ('market_observation_history','Fair <=64 identities and <=40-block slices; complete deterministic V4 tape and atomic checkpoint.',
     ['history.PonsHistory.history_batch','survivor.Runtime._increment_candidates','survivor.Runtime._increment','survivor.Runtime._append_tape','v4.collect_v4_activities','history.PonsHistory.append_block']),
    ('reorg_recovery','A canonical watermark mismatch removes historical authority, preserves controller and replays bounded slices from proven graduation.',
     ['survivor.Runtime._recover_reorg','history.PonsHistory.reset_after_reorg','history.PonsHistory.finish_recovery','history.PonsHistory.invalidate_discovery']),
    ('evidence_qualification','Graduation anchor, all last24h prices, current/previous30m flow, fresh V4 state and exact ordinary/double-size quotes. The realized-equity/turnover-capped strategy size is independent of the funding budget; the original five-second acquisition clock covers state, history and quotes.',
     ['survivor.Runtime.fresh_state','survivor.Runtime.fresh_quotes','survivor.Quotes.loss','survivor.Quotes._acquire','survivor.Runtime.reconstruct','survivor.Runtime.qualify','survivor_policy.evaluate_entry']),
    ('durable_decision','Fair independent qualification, History/Plane/Sleeve evidence and explicit disposition precede funding.',
     ['history.PonsHistory.qualification_turn','survivor.Runtime.step','attempts.Attempts.record','sleeve.SleeveReservations.observe']),
    ('funding_reservation_entry','Same realized-equity target in all cash states; available cash affects fresh commit only; capacity/breadth/generation fence.',
     ['survivor.Runtime._enter','commit.commit','book.PaperBook.reserve','sleeve.SleeveReservations.reserve','survivor.Runtime.validate_current']),
    ('monitoring','Funded native positions first; one position error cannot skip another; executable exit quote precedes candidate history.',
     ['survivor.Runtime._position','survivor.Runtime.exit_quote','survivor.Runtime.step','quotes.PinnedV4Reads.call','quotes.canonical_boundary','commit.monitor']),
    ('partial_realization_trail_adverse_flow','Survivor-owned -10%, +20%/25%, 12% then10% ordinary trail; existing persistent flow/creator/safety/max72h exits.',
     ['survivor_policy.risk_policy','risk.mark','commit.monitor','book.PaperBook.transition']),
    ('right_tail','Common >=2x 40% peak-profit giveback, original-unit risk after harvest/add.',
     ['risk.mark','continuation.reference_return','commit.monitor']),
    ('staged_add','Exactly one fresh complete strategy+execution requalification; inherited common add budget and native event.',
     ['commit.scale','continuation.scale_budget','book.PaperBook.transition','sleeve.SleeveReservations.reserve_scale']),
    ('bridge','The Current timing bridge lives on the Current controller; Survivor never sells/rebuys it. Same-asset reservation is execution-only.',
     ['continuation.bridge_state','sleeve.SleeveReservations.fill_blocker']),
    ('exit_settlement','Irreversible risk intent, fresh validated executable exit, native replay then sleeve release.',
     ['commit.monitor','survivor.Runtime.validate_exit','book.PaperBook.replay','sleeve.SleeveReservations.release']),
    ('restart','Exact committed block/hash/points/events/controller and native risk journal; no cached quote funds recovery.',
     ['history.PonsHistory.get','history.PonsHistory.append_block','commit.restore_risk','commit.handoff_ready','book.PaperBook.replay','sleeve.SleeveReservations.acknowledge_native'])]

EVIDENCE=[
    ('identity_lineage_native_quote',['already_graduated','non_native_quote_allocation_disabled'],
     'Exact current pin; compiled curve/deployer, fresh factory getLaunchedToken, token(), code, receipt and header; native pairToken zero.',
     'eth_chainId, eth_getBlockByNumber, eth_getTransactionReceipt, eth_getCode, eth_call',
     'Hash bodies reusable only after fresh numeric canonical membership; compiled identity has verified non-proxy CREATE2 provenance.',
     ['natural._authenticate_candidate','protocol.authenticate_curve','acquisition.SelectiveEvidenceContext.batch']),
    ('freshness',['stale_state_after_evidence'],
     'Original first observation -> complete evidence <=5s monotonic; chain timestamp lag separately reported; never reset by retries/restart.',
     'All calls retain original evidence_deadline; fresh numeric membership and current quote.',
     'No latest-state cache or reused old observation clock.', ['acquisition.evaluate_candidate','current.qualification_vector']),
    ('price_progress_launch_trajectory',['curve_progress','token_age','trajectory_history','curve_velocity','curve_deceleration','graduation_eta'],
     'Current real quote/threshold; launch zero-to-positive boundary; exact <=asof 15s/30s snapshots; age90..900s, progress45..88%, velocity>=200bps, ETA15..120s.',
     'Pinned eth_call realQuoteReserve; canonical eth_getBlockByNumber search.',
     '4096 header/static-state cache and launch hints; missing history is INCOMPLETE_EVIDENCE.', ['acquisition._trajectory','current.trajectory_metrics']),
    ('liquidity_capacity_cost',['position_size_zero','roundtrip_cost_unavailable','roundtrip_cost'],
     'Pinned reserves, real quote, fee/tax/snipe and fresh gas; 5% realized target limited by2%realquote/10%net/400bpsimpact; ordinary+2x stress capacity.',
     'eth_call getReserves/realQuoteReserve/reservedTokens/fees/currentSnipeTaxBps; eth_gasPrice; receipt gasUsed; exact compiled buy/sell math.',
     'Mutable gas only within current cost epoch/deadline; hash-pinned state reuse. No mark substituted for executable quantity. Capacity failure remains explicit.',
     ['current.entry_size','current.roundtrip_loss_bps','execution.resize','paper._entry_capacity']),
    ('flow_independence_concentration',['independent_breadth','buyer_growth','buy_sell_flow','net_demand_nonpositive','flow_deceleration','largest_buyer_concentration','top3_buyer_concentration'],
     'Complete selected-curve60s canonical ranges; current15s and preceding15s net/flow/buyers; three groups/newone/ratio1.1/largest45%/top3 65%. Independence is the coded group-address exclusion, not a proved sybil census.',
     '10-block eth_getLogs pages, receipt/header authentication of every returned member.',
     'Canonical block/transaction/log order; dedupe conflicts fail closed; complete vector uses all rows even if diagnostic rolling cache512 evicts.',
     ['window.canonical_window','acquisition._authenticate_window','current.demand_metrics']),
    ('creator_tax_distribution_snipe',['creator_distribution','creator_tax','snipe_tax_nonzero'],
     'Fresh factory deployer/creatorFeeRecipient; creator sale in current15s, creator tax<=200bps and recipient snipe exactlyzero.',
     'Canonical receipts/logs plus pinned currentSnipeTaxBps, fee/tax state and factory record.',
     'No public-trade omission can prove no creator sale; missing authority defers.', ['natural._authenticate_candidate','current.demand_metrics']),
    ('optional_diagnostics',['creator_adverse_history'],
     'Runtime passes no historical creator/wallet/relative-strength provider input. Repeat-wallet/convergence and quote-relative strength are diagnostics, not active hard gates. Creator adverse history is conditional only when supplied.',
     'No speculative historical wallet/creator RPC purchased.',
     'Does not substitute a missing active market fact.', ['current.wallet_convergence','current.qualification_vector']),
    ('entry_persistence_postgrad_add',[],
     'Fresh entry breadth>=50% retained; complete original trajectory+current15s quality; postgrad5..45s V4 tape; add rolling900s plus current authenticated state. No expired original early-entry age/ETA gate added to approved ongoing requalification.',
     'Small canonical log delta, current ABI state or V4 quote/lineage/tape.',
     'Durable900s accumulation; gap/reorg resets observation proof, does not reset position basis/HWM; incomplete add never commits.',
     ['paper._confirm_entry_delta','current.entry_signal_persistence','current.post_graduation_vector','current.ongoing_scale_requalification','current_history.CurrentHistory.invalidate'])]

BOUNDS=[
    ('A','Current age90..900s/progress45..88%/ETA15..120s; Survivor4h..7d; original bridge36h/Survivor hold72h','Frozen strategy domain; expiration is explicit.','unchanged'),
    ('A','Current/Suv entry and reentry quality, executable cost/impact, maxSurvivor positions2 and add ceilings','Economic/exposure rules; position limit applies after durable qualification.','unchanged'),
    ('B','Current window900s, Survivor exactlast24h+originalanchor+olderboundary; flowlast1h','Only facts outside future qualification windows are folded; proof prefix retained. Dense100001-price regression keeps whole vector identical.','repaired'),
    ('B','Immutable4096headers/launches/static,8192receipts/sharedRPC, plane diagnostic512rolling events and4096debug rows','Cache/debug eviction cannot evict candidate identity or decide strategy. Miss reacquires canonical fact. Hash bodies survive fork-alias invalidation.','separated'),
    ('B','Candidate-plane24h maintenance; Pons attempt audit7d maintenance','Pending/claim/outbox/native-position and Survivor controllers protect live identities; only explicit past horizon audit rows fold.','protected'),
    ('C','Survivor64candidate work batch,40blocks/turn,onegraduation authentication/turn,onequalification/turn','Durable attempt sequence rotates before provider work; bounded catch-up may be slow, never a count rejection.','repaired'),
    ('C','Current expensive worker and native lifecycle concurrency; sessions rotate at180requests','Cheap identity persists; position work has higher provider priority. Actual deadline throughput remains unproven.','retained'),
    ('D','10-block log pages,4V4log calls/physical batch,50RPC members,256candidate provider queue,0.5s admission interval','Transport shapes; priorityzero position admission cannot be refused because candidate queue is full. Requests/candidates defer under pressure.','repaired'),
    ('D','8192-block trajectory lookup, bounded32 sizing searches and4capacity steps','Missing unproven evidence is INCOMPLETE_EVIDENCE or EXECUTION_CAPACITY_UNAVAILABLE, not an invented reject. Extreme block-rate coverage remains unproven.','explicit'),
    ('E','512Current authenticated trades,2048source-tail slice,256V4perpool events,1000public log count','Removed accidental opportunity/evidence truncation. All complete selected-curve/window events feed frozen policy.','repaired'),
    ('E','Survivor64population discovery stop/32graduationburst cap and lowest-block starvation','No population stop; raw intake+cursor atomic, all nominees retained; failed batches rotate and another reorged candidate cannot skip valid candidates.','repaired'),
    ('E','Current campaign20000 attempt cap and65s blocking startup warmup','Campaign cap removed; complete canonical demand replaces warmup; restored positions serviced before observation startup. Bounded research modes remain isolated.','repaired'),
    ('E','Survivor qualification using allocatable cash; discovery suspended bycash; original unfilled-controller history lag','Fixed qualification target is realized equity; qualification durable first; unfunded controllers continue bounded history.','repaired'),
    ('E','Non-atomic history block pin and cached canonical-number aliases acrossforks','Observations+checkpoint atomic; numeric canonical membership revalidated, invalid aliases cleared; old observations cannot authorize fresh qualification/add.','repaired'),
    ('E','Survivor fixed quote ladder omitting exact turnover/funding sizes; quote completion restarting freshness','Exact requested and double-size probes are bought on demand; cached quote access retains the original state clock. Current/Survivor V4 reads batch state/cost with a fresh numeric membership boundary.','repaired')]


def build(root):
    from meme_machine.lanes.pons.identity import load
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY,POLICY_REVISION,POLICY_HASH
    from meme_machine.lanes.pons.pons_postgrad_survivor import STRATEGY_VERSION,POLICY_HASH as survivor_hash
    from operational.pons_finalization import SOURCE_COMMIT,SOURCE_TREE
    indices={};hashes={}
    for alias,relative in FILES.items():
        path=root/relative;raw=path.read_bytes();tree=ast.parse(raw)
        symbols={}
        def visit(node,prefix=''):
            for child in ast.iter_child_nodes(node):
                if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                    qualified=prefix+child.name;symbols[qualified]=child.lineno;visit(child,qualified+'.')
                else:visit(child,prefix)
        visit(tree);indices[alias]=symbols;hashes[relative]=hashlib.sha256(raw).hexdigest()
    def ref(text):
        alias,symbol=text.split('.',1)
        if symbol not in indices[alias]:raise ValueError('map_symbol_missing:'+text)
        return dict(file=FILES[alias],symbol=symbol,line=indices[alias][symbol])
    def lifecycle(rows):return [dict(stage=s,authority=a,refs=[ref(r) for r in rs]) for s,a,rs in rows]
    addresses={role:load(role)['address'] for role in ('pons_v2_factory','pons_deployer','pons_v2_hook','uniswap_v4_manager')}
    return dict(name='PONS_EVIDENCE_LIFECYCLE_MAP',schema='pons-lifecycle-map-v1',source_commit=SOURCE_COMMIT,
        source_tree=SOURCE_TREE,
        strategies=dict(current=dict(version=POLICY,revision=POLICY_REVISION,policy_hash=POLICY_HASH),
            survivor=dict(version=STRATEGY_VERSION,policy_hash=survivor_hash)),
        target_market=dict(chain_id=4663,addresses=addresses,
            current='All native-quote compiled Pons V2 curves observed through all-address CurveBuy/CurveSell; frozen early-entry domain is separate from discovery.',
            survivor='All authenticated Pons V2 PoolGraduated transitions to the registered native Uniswap V4 pool; independent4h..7d qualification.'),
        current=lifecycle(CURRENT),survivor=lifecycle(SURVIVOR),
        current_qualification_evidence=[dict(field=f,rejecting_gates=g,window_authority=w,provider_calls=p,reuse_failure=c,refs=[ref(r) for r in rs])
            for f,g,w,p,c,rs in EVIDENCE],
        bounds=[dict(category=c,bound=b,classification=r,status=s) for c,b,r,s in BOUNDS],
        runtime_selection=lifecycle([
            ('operational_current','Operational native Pons dispatch calls the selective cohort with campaign=True; the bounded default/research mode uses the same policy and is not the operational market domain.',
             ['entrypoint.run_native','cohort.run','paper.run_lifecycle']),
            ('operational_survivor','The directional composite setting MM_DIRECTIONAL_COMPOSITE_REQUIRED=1 creates the independent Survivor Worker from the selective cohort. Its native runtime/history/book are separate.',
             ['cohort.run','generic_history.Worker','survivor.Runtime.step']),
            ('legacy_continuation_research','continuation-v1-robinhood and its sample/cohort runners are preserved historical/research paths; the operational dispatcher does not select them.',
             ['legacy.qualification_vector','legacy_sample.run','legacy_cohort.run']),
            ('other_research','Natural observation and breakout/relative samples are preserved research paths; breakout allocation authority remains disabled. Shared natural identity/graduation/quote helpers supply the active implementations.',
             ['natural.run','graduation.run','breakout_sample.run','relative_sample.run'])]),
        provider_roles=dict(official_public='https://rpc.mainnet.chain.robinhood.com: discovery only, governed observation fallback retains range.',
            sequencer='wss://feed.mainnet.chain.robinhood.com: block/range clock only; no strategy value.',
            canonical='Authenticated chain4663 https://robinhood-mainnet.g.alchemy.com/v2/: Current/Survivor/positions, no public authority fallback.',
            admission='Pons/Ramses share existing endpoint governor; no budget ceiling raised; position class0 bypasses candidate queue-cap refusal.',
            immutable='By-hash headers/receipt/fully pinned state reusable; fresh canonical numeric membership remains mandatory; gas/latest values stay fresh.'),
        generic_components=lifecycle([
            ('candidate_evidence_plane','Shared durable identity/generation/outbox; Pons adapter and owned history tables carry Pons interpretation.',
             ['plane.Plane.observe','plane.Plane.claim','plane.Plane.finish','plane.Plane.maintain','broker.durable_cache']),
            ('provider_authority_admission_reuse','Chain/endpoint authority independent from resource scheduling.',
             ['authority.require_canonical','provider.PacedRpc._authority_guard','provider.PacedRpc._wire_params','admission.Admission.acquire','admission.next_ticket','immutable.Reuse.lookup']),
            ('native_accounting','Integer native units/exact accounting and durable realized-equity sleeve; no shared-capital feature change.',
             ['book.PaperBook.replay','sleeve.SleeveReservations.sizing_basis','sleeve.SleeveReservations.acknowledge_native','sleeve_policy.open_sleeve'])]),
        source_files_sha256=hashes,
        proof_limitations=['Source map and offline fixtures establish implementation paths; not a complete historical market census.',
            'Provider rate/deadline/capacity/cost acceptance remains unmeasurable from the retained archive.'])


def markdown(data):
    lines=['# PONS_EVIDENCE_LIFECYCLE_MAP','',f"Source operational commit: `{data['source_commit']}`. Engineering source symbols and hashes are validated from this tree.",'']
    for name,strategy in data['strategies'].items():
        lines.extend([f"{name.title()}: `{strategy['version']}`, policy hash `{strategy['policy_hash']}`.",''])
    for title,key in [('Runtime selection and preserved alternate paths','runtime_selection'),('Pons Current','current'),('Pons Survivor','survivor'),('Shared generic runtime','generic_components')]:
        lines.extend(['## '+title,'','| Stage | Authority / behavior | Files, classes and functions |','|---|---|---|'])
        for row in data[key]:
            refs='<br>'.join(f"[`{r['symbol']}`](../../{r['file']}#L{r['line']})" for r in row['refs'])
            lines.append('| '+row['stage']+' | '+row['authority']+' | '+refs+' |')
        lines.append('')
    lines.extend(['## Current qualification evidence','','| Field / active gates | Window and authority | Calls | Reuse and failure |','|---|---|---|---|'])
    for row in data['current_qualification_evidence']:
        lines.append('| '+row['field']+' / '+', '.join(row['rejecting_gates'])+' | '+row['window_authority']+' | '+row['provider_calls']+' | '+row['reuse_failure']+' |')
    lines.extend(['','## Every identified bound','','A=strategy domain, B=storage/retention, C=scheduling, D=provider, E=accidental opportunity bound. Only A decides eligibility; a missing proof always remains an explicit evidence failure.','','| Category | Bound | Treatment | State |','|---|---|---|---|'])
    for row in data['bounds']:lines.append('| '+row['category']+' | '+row['bound']+' | '+row['classification']+' | '+row['status']+' |')
    lines.extend(['','## Provider roles',''])
    for role,value in data['provider_roles'].items():lines.append('- **'+role+'**: '+value)
    lines.extend(['','## Limits of proof','']+['- '+v for v in data['proof_limitations']])
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='.');parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();data=build(Path(args.root));destination=Path(args.output_dir);destination.mkdir(parents=True,exist_ok=True)
    (destination/'PONS_EVIDENCE_LIFECYCLE_MAP.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    (destination/'PONS_EVIDENCE_LIFECYCLE_MAP.md').write_text(markdown(data))
    print(json.dumps(dict(current_stages=len(data['current']),survivor_stages=len(data['survivor']),source_files=len(data['source_files_sha256']))))


if __name__=='__main__':main()
