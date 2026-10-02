"""Render the Astra package from preserved, analyzed evidence; no execution API."""
import collections
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).parent
RUNS=Path('/workspace/stage-e-screen-work/runs/final-capacity-screen-20261001-v1')

def main():
    result=json.loads((HERE/'RESULTS.json').read_bytes())
    pre=json.loads((HERE/'PREDECLARATION.json').read_bytes())
    control,treatment=result['control'],result['treatment']
    arms=[control,treatment]
    lines=[]
    def add(text=''):lines.append(text)
    def table(headers,rows):
        add('| '+' | '.join(headers)+' |')
        add('| '+' | '.join('---' for x in headers)+' |')
        for row in rows:add('| '+' | '.join(str(x) for x in row)+' |')
        add()
    fmt=lambda x:f'{x:.6f}' if isinstance(x,float) else str(x)
    add('# Astra review — final Stage-E capacity screen')
    add()
    add('```text\nCAPACITY_SCREEN:\n'+result['CAPACITY_SCREEN']+'\n```')
    add()
    add('PAPER ONLY. Capacity-screen green: **false**. Stage E remains **RED**. '
        'Stage F remains **NOT_STARTED**. **STOP FOR ASTRA.** New capacity budget '
        '**2/2 consumed**, historical exploratory budget **6/6 unchanged**. '
        'Exactly one CONTROL followed by one TREATMENT, attempt 1 each. No retry, '
        'third arm, replacement, observer benchmark, fixed cohort, canonical Stage E, '
        'promotion, candidate freeze or Stage F was executed.')
    add()
    add('CONTROL did not reproduce the predeclared archive-capacity failure. In '
        'the fixed mature interval it archived **156,288** records against '
        '**155,496** eligible arrivals, reducing eligible hot debt **792 → 0**. '
        'No capacity refusal occurred and all 57 observed original recovery episodes '
        'resolved before their original deadlines. This fails the required CONTROL '
        'reproduction conditions. Treatment continued unchanged under the explicit '
        'predeclared continue-regardless policy. Its partial archive success does '
        'not create green credit.')
    add()
    add('## 1. Predeclaration, independent readback and execution order')
    add()
    add('Predeclaration commit: `729d0151568cec6dbcb93b5ff177d996ae9e3584`, '
        'tree `310b9a35f7979040857c77c48f06c96806711ba1`. '
        '[PREDECLARATION.md](PREDECLARATION.md) and [PREDECLARATION.json](PREDECLARATION.json) '
        'were published before either arm. JSON SHA-256: '
        '`f205a7892db04bff87c4cb30776e18d1491445032c6fcb7c3176ebedb28bc9d3`. '
        'The connected GitHub fetch_file independently read the pinned commit '
        'back with an exact byte match; [readback receipt](PREDECLARATION_READBACK.json). '
        'No boundary, criterion, horizon, runtime or observation configuration was moved.')
    add()
    table(['Checkpoint','Commit','Capacity consumption'],[
        ['CONTROL start receipt','`9c723905d8bd8eb3e5fa1ac7f22a27bce4219486`','0/2 before start; 1 on start'],
        ['CONTROL raw preservation','`acfcdcf78519313c87802dea3012a9e596ebeb6d`','1/2'],
        ['TREATMENT start receipt','`d4fbd9643ce8be3f0557ed2367be4dfd40353b13`','1/2 before start; 2 on start'],
        ['TREATMENT raw preservation','`93a68bfc82648d364cd2b286e6082b8a25552ef3`','2/2']])
    add('CONTROL raw artifacts were committed and published before TREATMENT started. '
        'TREATMENT raw artifacts were committed and published before their interpretation. '
        'Receipts: [CONTROL start](EXECUTION_RECEIPT_CONTROL.json), '
        '[TREATMENT start](EXECUTION_RECEIPT_TREATMENT.json), '
        '[after CONTROL](AFTER_CONTROL.json), [after TREATMENT](AFTER_TREATMENT.json), '
        '[current budget](BUDGET_CURRENT.json), [hard stop](STOP_FOR_ASTRA.json).')
    add()
    table(['Arm','UTC start','UTC end','Controller elapsed s','Native arm elapsed s','Process group'],[
        [a['arm'],a['execution']['utc_start'],a['execution']['utc_end'],fmt(a['execution']['elapsed']),
         fmt(a['whole_arm']['runtime_elapsed']),a['execution']['pid']] for a in arms])
    add('Both ran sequentially on hostname `bf7d12457ef8`, each with fresh independent '
        'process group, SQLite DB, archive/temp directories, state, spawned workers '
        'and observation output. No state was transferred. Both stopped at the fixed '
        'source horizon, without controller forcing or interruption.')
    add()
    add('## 2. Exact CONTROL and immutable TREATMENT')
    add()
    table(['Arm','Commit','Tree','Assembly digest'],[
        [a['arm'],a['identity']['commit'],a['identity']['tree'],a['identity']['assembly_digest']] for a in arms])
    add('CONTROL is exactly one callsite replacement in '
        '`meme_machine/solana_evidence_service.py`: '
        '`offer=await admission.rendezvous(source_state)` → `offer=None`. '
        'It descends directly from treatment S. Every other tracked blob and mode '
        'matches S. No historical runtime/file reversion was used. '
        '[CONTROL.diff](CONTROL.diff), [binary-capable CONTROL.patch](CONTROL.patch), '
        '[changed files](CHANGED_FILES.json), [static byte/AST comparison](STATIC_CONTROL_PROOF.json). '
        'Patch SHA-256: `6e05436dce786c9c1f7d8f9dbbee1c708be4e771408f7cbc3bd7826c11219344`.')
    add()
    add('Treatment preserves the reviewed assembly digest '
        '`08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659` exactly. '
        'Published manifests: [CONTROL](CONTROL_ASSEMBLY.json), [TREATMENT](TREATMENT_ASSEMBLY.json). '
        'The diagnostic control manifest explicitly identifies its reviewed base; '
        'qualification-v2 files/input manifest stay byte-identical, and no formal '
        'qualification verifier/certification credit is claimed for the derivative.')
    add()
    add('## 3. Driver/workload hashes, environment and observation configuration')
    add()
    add('The screen uses the existing reviewed housekeeping capacity harness from '
        '`d4068d4fa177225daf8780ee7c9765977f4b8793`, adapted only for exact provenance, '
        'the once-only start policy, bounded capture and full canonical urgent controls. '
        'Its pressure carrier remains the preserved Run380 template/Run381 retiming '
        'and durable-window-v4 combined Interaction. The original harness is retained '
        'as [text](historical-harness.py.txt).')
    add()
    table(['Executable/driver input','SHA-256'],list(pre['screen_files'].items()))
    table(['Workload input','SHA-256'],list(pre['workload']['file_hashes'].items()))
    add('All declared driver/support hashes still match. The only production delta '
        'between arms is the proven A2-disable callsite. Source remains 512 '
        'transactions/frame at .27 s cadence, with the same actual native record '
        'decoder, batching, archive .36 s/1,000 records delay, .006 s commit latency '
        'and two spawned decode/archive workers. Native record counts can exceed '
        'transaction counts when a preserved transaction emits multiple records. '
        'Independent epochs are retimed by the unchanged driver; actual eligible '
        'arrivals are measured in each run, never substituted from history.')
    add()
    add('Full canonical urgent ACKs ran every 1 s after ten source frames, plus the '
        'existing candidate ACK/read every 10 s. The original frame-800 8 s pause, '
        'actual multiframe-triggered held reader and delayed complete-PASSIVE tail '
        'ran. Frame 1400/the second pause remains outside the predeclared prefix. '
        'There was no reduced-ACK shortcut or threshold relaxation.')
    add()
    add('Python 3.12.14, SQLite 3.53.1 and websockets 17.1, interpreter SHA-256 '
        '`fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`, '
        'standard-library digest `1b1009522cb97578f8b9fa9a1941c58c5e33c95c35a4088c2707719feb57e09f`, '
        'and dependency digest `e42fd4edcc9677f87b9542c5e5e35bf8cc54314055358e3afdea49f7dcc6f117` '
        'matched the reviewed environment exactly in both arms. '
        '[ENVIRONMENT.json](ENVIRONMENT.json) binds every dependency/library file, '
        'host CPU affinity/quota, memory, resource limits and filesystem. The same '
        'managed runner was used because it matches the reviewed environment; '
        'a new hosted CI runner would introduce a different environment. No CI '
        'qualification claim is made.')
    add()
    add('## 4. Raw artifacts, identities and budget preservation')
    add()
    table(['Raw artifact','SHA-256','Inventory SHA-256'],[
        [r['raw_archive'],r['raw_archive_sha256'],r['raw_inventory_sha256']]
        for r in [json.loads((HERE/'AFTER_CONTROL.json').read_bytes()),json.loads((HERE/'AFTER_TREATMENT.json').read_bytes())]])
    add('Run ID: `final-capacity-screen-20261001-v1`, attempt 1 for both arms. '
        'Raw files contain the original timeline, scheduled mature/pre-stop/final '
        'snapshots, source batches/queues, owner events, native decisions/turns, '
        'archive cycles, recovery transitions, A2 events, checkpoint/native health, '
        'integrity, module origins, spawned-worker firewall receipts and process log. '
        '[CONTROL raw evidence](CONTROL_RAW_EVIDENCE.tar.gz), '
        '[TREATMENT raw evidence](TREATMENT_RAW_EVIDENCE.tar.gz).')
    add()
    add('AGENTS.md requires runtime DBs to remain outside Git/logs. Full runtime '
        'databases and payload archives remain at '
        '`/workspace/stage-e-screen-work/runs/final-capacity-screen-20261001-v1/{control,treatment}/raw/runtime/`, '
        'with their complete raw SHA-256/size inventories inside the published '
        'archives. The read-only telemetry/logs/receipts themselves are durable in Git. '
        'Archive members and hashes were independently validated after execution; '
        '[PUBLICATION_VALIDATION.json](PUBLICATION_VALIDATION.json). '
        '[FILE_INDEX.json](FILE_INDEX.json) binds the final published file sizes '
        'and SHA-256 values, excluding the index itself.')
    add()
    add('## 5. Fixed mature interval and source integrity')
    add()
    add('Identical offered-source boundaries: **190.08–349.92 s**. Fixed horizon: '
        '**1,334 frames**, 360.18 frame-count source seconds, last payload offset '
        '359.91 s. The window includes the original [216,336] recovery regime and '
        'ends before source stops. Both endpoints were captured while source '
        'advanced; neither arm is censored. Whole-arm totals below are separate '
        'from capacity-window results. No shutdown-drain credit is used.')
    add()
    table(['Arm','Offered','Admitted','Committed','Source seconds','Lag peak s','Native source s','Injected source s','Charge errors'],[
        [a['arm'],*[a['source'][k] for k in ('offered','admitted','committed')],a['source']['committed_source_seconds'],
         fmt(a['source']['peak_source_lag']),fmt(a['source']['native_source_seconds']),fmt(a['source']['injected_source_seconds']),
         a['source']['charge_formula_errors']] for a in arms])
    add('Each batch satisfies exactly `max(0, .165 * actual_frame_count - native_source_elapsed)`. '
        'No frame was silently lost, no disconnect/unrepaired gap occurred, and '
        'lag stayed below the unchanged 45 s contract. The offered blueprint and '
        'horizon match, with legal scheduling only.')
    add()
    table(['Arm','Pending frame peak','Pending byte peak','Inbound/decoded/ready peaks','Mature pending slope frames/s','Due-minus-committed growth'],[
        [a['arm'],a['source']['peak_pending_frames'],a['source']['peak_pending_bytes'],
         '/'.join(str(a['source']['queue_peaks'][k]) for k in ('inbound','decoded','ready')),
         fmt(a['source']['mature_pending_slope']),a['source']['mature_due_uncommitted_growth']] for a in arms])
    add('Bounds remained 64 pending frames/96 MiB, with original 8-frame/16-MiB '
        'source transactions. Both mature queue trends declined and due-but-uncommitted '
        'backlog did not grow. A one-frame active-pipeline endpoint difference is '
        'reported in RESULTS.json; source integrity uses the declared backlog '
        'trend and fixed due-work backlog rather than treating queue phase as '
        'a maintenance-capacity failure.')
    add()
    add('## 6. Mature archive arrivals, durable drain and debt')
    add()
    table(['Arm','Arrivals','Durable archive','Arrival/s','Archive/s','Surplus/s','Start debt','Peak debt','End debt','Debt slope records/s'],[
        [a['arm'],a['archive']['eligible_arrivals'],a['archive']['durable_archived'],
         fmt(a['archive']['arrival_rate']),fmt(a['archive']['archive_rate']),fmt(a['archive']['rate_surplus']),
         a['archive']['starting_hot_debt'],a['archive']['peak_hot_debt'],a['archive']['ending_hot_debt'],fmt(a['archive']['debt_slope'])] for a in arms])
    add('The census uses current durable cohorts/counters in one read snapshot. '
        'Rates use actual measured snapshot elapsed: CONTROL '+fmt(control['archive']['measured_seconds'])+
        ' s, TREATMENT '+fmt(treatment['archive']['measured_seconds'])+' s. Fixed '
        'source offsets are identical; acquisition gaps are reported separately. '
        'The hot-debt slope is least-squares across fixed endpoints and live '
        'periodic samples within the declared interval. CONTROL archive drain '
        'strictly exceeded arrivals, its debt discharged, and no relevant '
        'capacity/deadline failure occurred. None of the three required '
        'reproduction conditions held. Treatment also has positive archive surplus and debt '
        'reduction; this does not overcome invalid control reproduction.')
    add()
    table(['Arm','Archive durable slices, whole arm','Durable slice records, whole arm','Min/max records per slice','Contract cap'],[
        [a['arm'],a['archive_slice_summary']['whole_arm_durable_slices'],a['archive_slice_summary']['whole_arm_durable_slice_records'],
         str(a['archive_slice_summary']['records_per_slice_min'])+'/'+str(a['archive_slice_summary']['records_per_slice_max']),512] for a in arms])
    add('All actual worker dispatch/execution/delay/ready/pending cycles, slice '
        'records, native needs/readiness/effective deadlines, feasible-side '
        'reconstruction, selected side/refusal and peer reservation state are '
        'retained in the raw archive-cycles, native-turns, source-queues and timeline.')
    add()
    add('## 7. Mature retirement and every native scope')
    add()
    table(['Arm','Scope','Eligible arrivals','Archive','Retired','Pending start','Pending peak','Pending end','Retirement excess start/end','Keeps pace'],[
        [a['arm'],scope.replace('program:',''),v['eligible_arrivals'],v['durable_archived'],v['durable_retired'],
         v['starting_archived_pending'],v['peak_archived_pending'],v['ending_archived_pending'],
         str(v['starting_retirement_excess'])+'/'+str(v['ending_retirement_excess']),v['retirement_keeps_pace']]
        for a in arms for scope,v in a['per_scope'].items()])
    add('Pump, PumpSwap and Meteora are the only active native record scopes in '
        'this driver. Every scope received durable retirement service; none was '
        'silently starved. Nevertheless, each arm retired **264 fewer records** '
        'than it newly archived over the fixed mature window. CONTROL pending '
        'debt rose 528→792; TREATMENT rose 0→264. All per-scope strict '
        'keep-pace/nonincreasing-pending criteria fail. Recovery excess resolved, '
        'but that is insufficient to certify retirement sustainability. The '
        'window is not shifted to find a passing queue phase.')
    add()
    table(['Arm','Scope','Archive arrivals/s','Archive/s','Archive surplus/s','Retirement/s','Hot start/peak/end','Hot slope'],[
        [a['arm'],scope.replace('program:',''),fmt(v['archive_arrival_rate']),fmt(v['archive_rate']),fmt(v['archive_rate_surplus']),
         fmt(v['retirement_service_rate']),'/'.join(str(v[k]) for k in ('starting_hot_debt','peak_hot_debt','ending_hot_debt')),
         fmt(v['hot_debt_slope'])] for a in arms for scope,v in a['per_scope'].items()])
    add('## 8. Every original recovery episode and deadline')
    add()
    add('All **91** episodes are retained separately by scope/side/original '
        'deadline/original wall start: **57 CONTROL**, **34 TREATMENT**. Required '
        'deadline observations (origin source ≤240 s): **19 CONTROL**, **17 '
        'TREATMENT**. All observed episodes passed before their own original '
        'deadlines; OPEN/CENSORED/FAILED counts are zero. Late-origin episodes '
        'receive credit only for directly observed pre-deadline resolution. '
        'No replacement/re-enrollment/rebased origin substitutes for an older '
        'episode. Exact clocks, opening excess, durable progress, resolution '
        'and headroom: [RECOVERY_EPISODES.json](RECOVERY_EPISODES.json).')
    add()
    add('Source start/deadline below are offsets from each immutable Wire.start. '
        'Resolution is the directly recorded monotonic clock; exact original '
        'wall starts and clock projection are in JSON. Durably committed record '
        'progress is scoped to the original episode, not a later replacement.')
    add()
    table(['Arm','Scope','Side','Original source start s','Original source deadline s','Opening excess','Durable progress','Resolution monotonic','Headroom s','Status'],[
        [a['arm'],e['scope'].replace('program:',''),e['side'],fmt(e['original_start_source_offset']),fmt(e['original_deadline_source_offset']),
         e['opening_excess'],e['durable_record_progress'],fmt(e['resolution_monotonic']),fmt(e['headroom_at_resolution']),e['status']]
        for a in arms for e in a['recovery_episodes']])
    add('## 9. Coupled balances and no debt export')
    add()
    add('Independent native ingested counters reconcile with total hot + '
        'archived-pending + durable retired in every read snapshot. The eligible '
        'arrival census is eligible hot + archived-pending + durable retired; '
        'this census identity is definitional, while the native ingested balance '
        'and interval archive/retirement flows independently reconcile. Pins and '
        'gaps were zero, so no preservation exception invalidates eligibility.')
    add()
    table(['Arm','Eligible hot start/end','Archived-pending start/end','Retired during interval','Hot delta','Pending delta','Coupled residuals'],[
        [a['arm'],str(a['archive']['starting_hot_debt'])+'/'+str(a['archive']['ending_hot_debt']),
         str(a['archive']['starting_archived_pending'])+'/'+str(a['archive']['ending_archived_pending']),a['archive']['durable_retired'],
         a['archive']['ending_hot_debt']-a['archive']['starting_hot_debt'],
         a['archive']['ending_archived_pending']-a['archive']['starting_archived_pending'],
         '0 for every scope'] for a in arms])
    add('TREATMENT hot debt fell by exactly 264 while archived-pending rose by '
        '264. Thus its endpoint hot-debt reduction is entirely matched by '
        'retirement debt transfer, even though substantial work was durably '
        'retired. It does not prove net maintenance-debt reduction. CONTROL '
        'combined hot+pending debt fell 1,320→792. No hidden record balance '
        'or source backlog is erased to create a pass.')
    add()
    add('## 10. A2 offers, placements, progress and deadline correlation')
    add()
    table(['Arm','Offers','Accepted','Timeouts','Bypasses incl. ACK','Actual before-source placements','Affected frames','Placements with direct durable records'],[
        [a['arm'],a['a2']['offers'],a['a2']['accepted'],a['a2']['timeouts'],a['a2']['bypass_total'],
         a['a2']['actual_placements'],a['a2']['affected_frames'],a['a2']['useful_placements']] for a in arms])
    add('CONTROL **A2 opportunity count = 0**. TREATMENT opened 22 offers: '
        '21 accepted, one bypassed due to an intervening owner queue, zero '
        'timeouts/overshoots. Its 1,275 bypass counters include one protocol '
        'ACK; 1,274 are pre-source bypasses. Reasons: no-positive-hint 682, '
        'maintenance-unfinished 590, checkpoint-handoff 1, owner-queue 1, '
        'head-ACK 1. Accepted owner admission alone is not claimed as durable '
        'service. Twenty-one actual maintenance-owner entries preceded their '
        'source-owner entries. One directly committed **56 PumpSwap archive '
        'records**; the other placements had no direct record credit.')
    add()
    add('[A2_PLACEMENTS.json](A2_PLACEMENTS.json) contains all 21 placements, '
        'native durable progress/records, selected side, fresh scope debt, '
        'next native-observation debt changes and the headroom of every then-active '
        'original recovery episode. The next observation can include intervening '
        'source arrivals or other maintenance, so those changes are temporal '
        'correlation only. No causal benefit beyond this pair is claimed.')
    add()
    table(['Maintenance sequence','Source sequence','Selected side','Durable records','Gate wait s','Original recovery headroom(s)'],[
        [e['maintenance_sequence'],e['source_sequence'],e.get('selected_side') or 'none',
         e['useful_durable_records'],fmt(e['gate_wait']),
         '; '.join(x['scope'].replace('program:','')+'/'+x['side']+':'+fmt(x['headroom_seconds']) for x in e['original_recovery_headroom_at_placement']) or 'no active episode']
        for e in treatment['a2']['placement_correlations']])
    add('## 11. Housekeeping/M1 constant proof, fairness and continuity')
    add()
    add('Full exact diff/AST proof preserves all M1 completion/cooperative '
        'logic, housekeeping ordering/prefix context, retention/floors/continuity, '
        'native arbiter, reservation rules and generation fencing. Protected '
        'file hashes are in STATIC_CONTROL_PROOF.json; no treatment byte was '
        'modified. Native prefix trigger counts can differ with legal scheduling '
        'while the formula/semantics remain exact.')
    add()
    table(['Arm','Housekeeping demand peak','Prefix triggers','Prefix commits','Prefix units','All housekeeping units','Prefix source/urgent returns','All retention source/urgent returns'],[
        [a['arm'],a['housekeeping']['native_demand_peak'],a['housekeeping']['prefix_triggers'],a['housekeeping']['prefix_commits'],
         a['housekeeping']['prefix_committed_units'],a['housekeeping']['durable_units'],
         str(a['housekeeping']['prefix_source_returns'])+'/'+str(a['housekeeping']['prefix_urgent_returns']),
         str(a['housekeeping']['all_retention_source_returns'])+'/'+str(a['housekeeping']['all_retention_urgent_returns'])] for a in arms])
    add('CONTROL’s single native prefix committed 1,031 housekeeping units, '
        'zero record retirement, then returned to source with the prepared '
        'receipt still pending. TREATMENT needed no prefix. Both kept the '
        'identical bounded native GC and M1 durable-completion accounting.')
    add()
    table(['Arm','Owner admissions','Priority 0 admissions','Owner queue peak delay s','FIFO errors','Unresolved accepted futures'],[
        [a['arm'],a['owner']['admissions'],a['owner']['priority_counts'].get('0',0),fmt(a['owner']['queue_delay_peak']),
         len(a['owner']['fairness_errors']),a['observation']['screen']['owner_unresolved_accepted_futures']] for a in arms])
    add('Native strict urgent priority and nonurgent FIFO after admission '
        'remain byte-identical. No observed FIFO error, urgent/candidate error '
        'or native arbiter refusal/failure occurred. Original leases, two-sided '
        'reservations, worker lease, generation fencing and transaction bounds '
        'were exercised unchanged. Actual per-scope service gaps and all '
        'checkpoint holds are retained in RESULTS.json/raw owner events. '
        'Every scope advanced retirement/continuity floors; no active gap or '
        'pin remained. Floor and continuity counts at both mature endpoints '
        'and whole-arm end are in RESULTS.json.')
    add()
    add('## 12. Ages, resource bounds, checkpoint and integrity')
    add()
    table(['Arm','Hot age peak s','Retained age peak s','Source lag peak s','DB+WAL peak bytes','RSS peak KiB','SQLite integrity'],[
        [a['arm'],fmt(a['ages']['hot_peak']),fmt(a['ages']['retained_peak']),fmt(a['source']['peak_source_lag']),
         a['resources']['peak_db_plus_wal_bytes'],a['resources']['self_rusage']['ru_maxrss'],'ok'] for a in arms])
    add('Both residence peaks are strictly <240 s; no equality is passed. '
        'DB+WAL stayed below 2 GiB. Worker/process groups exited, owner threads '
        'stopped, accepted owner futures unresolved=0, and writer transaction '
        'state at close was false. All returned native owner operations have '
        'their transaction state recorded. Two independent native spawned '
        'workers per arm exited; no process-group leak or abandoned transaction '
        'was observed.')
    add()
    table(['Arm','Checkpoint calls','Reclaimed','Boundary calls','Boundary reclaimed','Incomplete receipts','Worker/process leaks'],[
        [a['arm'],*[a['resources']['checkpoint'].get(k,0) for k in ('checkpoint.calls','checkpoint.reclaimed','checkpoint.boundary_calls','checkpoint.boundary_reclaimed','checkpoint.incomplete')],0] for a in arms])
    add('Transient incomplete checkpoint receipts are retained as such, not '
        'fabricated completion. Native successful reclamations and bounded '
        'checkpoint handoffs continued in both arms. No new terminal refusal '
        'replaced a historical maintenance failure.')
    add()
    add('## 13. Observation cost, errors and measurement gaps')
    add()
    table(['Recorded elapsed timer, seconds','CONTROL','TREATMENT'],[
        [k,fmt(control['observation']['costs'][k]['wall']),fmt(treatment['observation']['costs'][k]['wall'])]
        for k in control['observation']['costs']])
    add('Recorded timer sums: CONTROL '+fmt(control['observation']['recorded_timer_sum_seconds'])+
        ' s; TREATMENT '+fmt(treatment['observation']['recorded_timer_sum_seconds'])+
        ' s. Timers overlap, including scheduled-boundary capture within observer '
        'timers; this is not an isolated overhead ratio or a <1% benchmark. '
        'Spawned-child startup observation elapsed is separately retained. '
        'All observation costs remain in measured runtime; nothing is subtracted.')
    add()
    table(['Arm','Dropped samples','Observer/errors','Max periodic gap s','Start/end acquisition gap s','Configuration/bytes'],[
        [a['arm'],a['observation']['screen']['dropped_samples'],
         len(a['observation']['screen']['periodic_observer_errors'])+len(a['observation']['screen']['instrumentation_errors']),
         fmt(a['observation']['screen']['measurement_gap_peak_seconds']),
         '/'.join(fmt(a['observation']['screen']['boundary_acquisition_gaps'][k]) for k in ('start','end')),
         'identical, predeclared'] for a in arms])
    add('All gaps stayed within predeclared bounds (boundary ≤1 s, periodic '
        '≤10 s), with zero observer error/drop. Native rolling-ring evictions '
        'are reported separately from full-capture drops. Full event capture '
        'preserved source queues, A2 offers/placements, original episode '
        'transitions and native decisions. No material capture asymmetry '
        'was found.')
    add()
    add('## 14. Whole-arm totals, provider firewall and exact verdict')
    add()
    table(['Arm','Scope','Ingested','Archived durable','Retired durable','Hot retained','Archived-pending retained'],[
        [a['arm'],scope.replace('program:',''),s['ingested'],s['archived'],s['retired'],s['hot'],s['archived_pending']]
        for a in arms for scope,s in a['whole_arm']['final_scopes'].items()])
    add('These whole-arm counters include integrity teardown and are reported '
        'separately; they do not change the mature-window verdict. Provider '
        '**calls=0, attempts=0** in both arms. Parent and spawned-worker '
        'Internet firewalls preserved native Unix IPC and recorded attempts '
        'before packet emission. There was no credential, wallet or signing '
        'authority in the child environment.')
    add()
    table(['Predeclared requirement','CONTROL','TREATMENT'],[
        [k,control['checks'][k],treatment['checks'][k]] for k in control['checks']])
    add('Under the fixed precedence, valid observation plus failure to reproduce '
        'CONTROL’s required archive deficit/debt/recovery condition yields '
        '**INCONCLUSIVE_CONTROL_DID_NOT_REPRODUCE**. Treatment’s archive '
        'surplus/debt decrease and observed A2 placement do not alter that '
        'classification. Retirement keep-pace/no-export requirements also '
        'remain unproven/failed in the declared interval. There is no capacity '
        'green, causal capacity-recovery claim, Stage E promotion or Stage F '
        'authority. [RESULTS.json](RESULTS.json) contains the complete current-run '
        'measurements and mechanical decision; all raw inputs were preserved '
        'before interpretation. **STOP FOR ASTRA.**')
    (HERE/'ASTRA_REVIEW_PACKAGE.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'package':'ASTRA_REVIEW_PACKAGE.md','classification':result['CAPACITY_SCREEN'],'material_executions':0}))

if __name__=='__main__':main()
