# Astra review — final Stage-E capacity screen

```text
CAPACITY_SCREEN:
INCONCLUSIVE_CONTROL_DID_NOT_REPRODUCE
```

PAPER ONLY. Capacity-screen green: **false**. Stage E remains **RED**. Stage F remains **NOT_STARTED**. **STOP FOR ASTRA.** New capacity budget **2/2 consumed**, historical exploratory budget **6/6 unchanged**. Exactly one CONTROL followed by one TREATMENT, attempt 1 each. No retry, third arm, replacement, observer benchmark, fixed cohort, canonical Stage E, promotion, candidate freeze or Stage F was executed.

CONTROL did not reproduce the predeclared archive-capacity failure. In the fixed mature interval it archived **156,288** records against **155,496** eligible arrivals, reducing eligible hot debt **792 → 0**. No capacity refusal occurred and all 57 observed original recovery episodes resolved before their original deadlines. This fails the required CONTROL reproduction conditions. Treatment continued unchanged under the explicit predeclared continue-regardless policy. Its partial archive success does not create green credit.

## 1. Predeclaration, independent readback and execution order

Predeclaration commit: `729d0151568cec6dbcb93b5ff177d996ae9e3584`, tree `310b9a35f7979040857c77c48f06c96806711ba1`. [PREDECLARATION.md](PREDECLARATION.md) and [PREDECLARATION.json](PREDECLARATION.json) were published before either arm. JSON SHA-256: `f205a7892db04bff87c4cb30776e18d1491445032c6fcb7c3176ebedb28bc9d3`. The connected GitHub fetch_file independently read the pinned commit back with an exact byte match; [readback receipt](PREDECLARATION_READBACK.json). No boundary, criterion, horizon, runtime or observation configuration was moved.

| Checkpoint | Commit | Capacity consumption |
| --- | --- | --- |
| CONTROL start receipt | `9c723905d8bd8eb3e5fa1ac7f22a27bce4219486` | 0/2 before start; 1 on start |
| CONTROL raw preservation | `acfcdcf78519313c87802dea3012a9e596ebeb6d` | 1/2 |
| TREATMENT start receipt | `d4fbd9643ce8be3f0557ed2367be4dfd40353b13` | 1/2 before start; 2 on start |
| TREATMENT raw preservation | `93a68bfc82648d364cd2b286e6082b8a25552ef3` | 2/2 |

CONTROL raw artifacts were committed and published before TREATMENT started. TREATMENT raw artifacts were committed and published before their interpretation. Receipts: [CONTROL start](EXECUTION_RECEIPT_CONTROL.json), [TREATMENT start](EXECUTION_RECEIPT_TREATMENT.json), [after CONTROL](AFTER_CONTROL.json), [after TREATMENT](AFTER_TREATMENT.json), [current budget](BUDGET_CURRENT.json), [hard stop](STOP_FOR_ASTRA.json).

| Arm | UTC start | UTC end | Controller elapsed s | Native arm elapsed s | Process group |
| --- | --- | --- | --- | --- | --- |
| control | 2026-10-01T23:27:28Z | 2026-10-01T23:33:35Z | 367.076406 | 361.949128 | 3464 |
| treatment | 2026-10-01T23:40:15Z | 2026-10-01T23:46:22Z | 366.394828 | 361.153007 | 4258 |

Both ran sequentially on hostname `bf7d12457ef8`, each with fresh independent process group, SQLite DB, archive/temp directories, state, spawned workers and observation output. No state was transferred. Both stopped at the fixed source horizon, without controller forcing or interruption.

## 2. Exact CONTROL and immutable TREATMENT

| Arm | Commit | Tree | Assembly digest |
| --- | --- | --- | --- |
| control | 19b4244d6c09eeebab37319784109b876c94a0d4 | dda7f9df08fa258d9856b5521ada10a7cb8e8b25 | 61bf11629765f7251767a1e868002ad7f099a51d0112ff88eb490e90ac26f7f9 |
| treatment | 7a516a6a92be9347661ac0e7f560971c171a0931 | 9da7d1e1625ba04c1437c63606c90f5e293bdba7 | 08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659 |

CONTROL is exactly one callsite replacement in `meme_machine/solana_evidence_service.py`: `offer=await admission.rendezvous(source_state)` → `offer=None`. It descends directly from treatment S. Every other tracked blob and mode matches S. No historical runtime/file reversion was used. [CONTROL.diff](CONTROL.diff), [binary-capable CONTROL.patch](CONTROL.patch), [changed files](CHANGED_FILES.json), [static byte/AST comparison](STATIC_CONTROL_PROOF.json). Patch SHA-256: `6e05436dce786c9c1f7d8f9dbbee1c708be4e771408f7cbc3bd7826c11219344`.

Treatment preserves the reviewed assembly digest `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659` exactly. Published manifests: [CONTROL](CONTROL_ASSEMBLY.json), [TREATMENT](TREATMENT_ASSEMBLY.json). The diagnostic control manifest explicitly identifies its reviewed base; qualification-v2 files/input manifest stay byte-identical, and no formal qualification verifier/certification credit is claimed for the derivative.

## 3. Driver/workload hashes, environment and observation configuration

The screen uses the existing reviewed housekeeping capacity harness from `d4068d4fa177225daf8780ee7c9765977f4b8793`, adapted only for exact provenance, the once-only start policy, bounded capture and full canonical urgent controls. Its pressure carrier remains the preserved Run380 template/Run381 retiming and durable-window-v4 combined Interaction. The original harness is retained as [text](historical-harness.py.txt).

| Executable/driver input | SHA-256 |
| --- | --- |
| execute_arm.py | 5800ee267208f410ec773783cc004f645a4d17d749253306d023afb751397f57 |
| harness.py | d5992be6cc70fa60875284a28949485ee7cdadc2e94e7195035e028c0b2a2902 |
| historical-harness.py.txt | caa547cd814d32cd90be214f64b5b044af573d387722844e4a3cf707c5f2a67f |
| prepare.py | e312ffa9379f81148bb9eb7bf2f196305cd905eebe71d3bed675552a00ca0cbc |
| publish.py | 2c1d50dd2efc489c18c83075185494a037c5a76f8333e0fc06b1749c8862c270 |
| screen_support.py | aeb898920cb7cbf5b26ae3455e265cde0594b171662817d62b1ecb5e9b303435 |

| Workload input | SHA-256 |
| --- | --- |
| certification/combined_observer.py | bcbbcf46a123fccbc3268e745d3d0b8ca505ae73710d4ac262b9789c330b28af |
| certification/combined_pressure.py | 8f7dd4a5d5b3538a34cc034ebeaa37ef10eabdcd44f3cbd420532fa28fd0803a |
| certification/run381_pressure.py | fa1372179022c1561644d2e3932c8f7e218d49ebfe02400e568824b1359323cd |
| certification/tests/fixtures/run380-production-templates.json.gz | 6c3d4c0689a4886c0e1fedc95a758e634fb2de1b2cd8b93bec580e40ad008376 |
| tests/test_run380_production_pressure.py | 08e8fd7a43b1b0fa4cdcdb469b2e837e99e89d5338f724bc1bd21a4647419b47 |

All declared driver/support hashes still match. The only production delta between arms is the proven A2-disable callsite. Source remains 512 transactions/frame at .27 s cadence, with the same actual native record decoder, batching, archive .36 s/1,000 records delay, .006 s commit latency and two spawned decode/archive workers. Native record counts can exceed transaction counts when a preserved transaction emits multiple records. Independent epochs are retimed by the unchanged driver; actual eligible arrivals are measured in each run, never substituted from history.

Full canonical urgent ACKs ran every 1 s after ten source frames, plus the existing candidate ACK/read every 10 s. The original frame-800 8 s pause, actual multiframe-triggered held reader and delayed complete-PASSIVE tail ran. Frame 1400/the second pause remains outside the predeclared prefix. There was no reduced-ACK shortcut or threshold relaxation.

Python 3.12.14, SQLite 3.53.1 and websockets 17.1, interpreter SHA-256 `fa67443527ed9647f760d807e2a38f26340757123e643c4639cf273ed15d5ea7`, standard-library digest `1b1009522cb97578f8b9fa9a1941c58c5e33c95c35a4088c2707719feb57e09f`, and dependency digest `e42fd4edcc9677f87b9542c5e5e35bf8cc54314055358e3afdea49f7dcc6f117` matched the reviewed environment exactly in both arms. [ENVIRONMENT.json](ENVIRONMENT.json) binds every dependency/library file, host CPU affinity/quota, memory, resource limits and filesystem. The same managed runner was used because it matches the reviewed environment; a new hosted CI runner would introduce a different environment. No CI qualification claim is made.

## 4. Raw artifacts, identities and budget preservation

| Raw artifact | SHA-256 | Inventory SHA-256 |
| --- | --- | --- |
| CONTROL_RAW_EVIDENCE.tar.gz | 7d61af5552f2c82483f2e871e77921ad39f238ef7b2df1848d653345f172900d | dcbe1a175b33b46e6344f242603ffdc57201d1497932d1de26fec4ed2153b4ca |
| TREATMENT_RAW_EVIDENCE.tar.gz | c2b55267634d03cd460045b019e8642d6e8585a6a0f8aa0b9a8a9f20976a59a1 | 335a3fb76fe6e846fcb7e44a6822e1e91b108f9fe650dd269cea018ca1ccd1e6 |

Run ID: `final-capacity-screen-20261001-v1`, attempt 1 for both arms. Raw files contain the original timeline, scheduled mature/pre-stop/final snapshots, source batches/queues, owner events, native decisions/turns, archive cycles, recovery transitions, A2 events, checkpoint/native health, integrity, module origins, spawned-worker firewall receipts and process log. [CONTROL raw evidence](CONTROL_RAW_EVIDENCE.tar.gz), [TREATMENT raw evidence](TREATMENT_RAW_EVIDENCE.tar.gz).

AGENTS.md requires runtime DBs to remain outside Git/logs. Full runtime databases and payload archives remain at `/workspace/stage-e-screen-work/runs/final-capacity-screen-20261001-v1/{control,treatment}/raw/runtime/`, with their complete raw SHA-256/size inventories inside the published archives. The read-only telemetry/logs/receipts themselves are durable in Git. Archive members and hashes were independently validated after execution; [PUBLICATION_VALIDATION.json](PUBLICATION_VALIDATION.json). [FILE_INDEX.json](FILE_INDEX.json) binds the final published file sizes and SHA-256 values, excluding the index itself.

## 5. Fixed mature interval and source integrity

Identical offered-source boundaries: **190.08–349.92 s**. Fixed horizon: **1,334 frames**, 360.18 frame-count source seconds, last payload offset 359.91 s. The window includes the original [216,336] recovery regime and ends before source stops. Both endpoints were captured while source advanced; neither arm is censored. Whole-arm totals below are separate from capacity-window results. No shutdown-drain credit is used.

| Arm | Offered | Admitted | Committed | Source seconds | Lag peak s | Native source s | Injected source s | Charge errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 1334 | 1334 | 1334 | 360.18 | 8.198793 | 114.270000 | 105.917681 | 0 |
| treatment | 1334 | 1334 | 1334 | 360.18 | 8.692260 | 111.037242 | 109.106984 | 0 |

Each batch satisfies exactly `max(0, .165 * actual_frame_count - native_source_elapsed)`. No frame was silently lost, no disconnect/unrepaired gap occurred, and lag stayed below the unchanged 45 s contract. The offered blueprint and horizon match, with legal scheduling only.

| Arm | Pending frame peak | Pending byte peak | Inbound/decoded/ready peaks | Mature pending slope frames/s | Due-minus-committed growth |
| --- | --- | --- | --- | --- | --- |
| control | 21 | 85722105 | 14/13/13 | -0.036889 | 0 |
| treatment | 21 | 85722105 | 14/17/12 | -0.034266 | 0 |

Bounds remained 64 pending frames/96 MiB, with original 8-frame/16-MiB source transactions. Both mature queue trends declined and due-but-uncommitted backlog did not grow. A one-frame active-pipeline endpoint difference is reported in RESULTS.json; source integrity uses the declared backlog trend and fixed due-work backlog rather than treating queue phase as a maintenance-capacity failure.

## 6. Mature archive arrivals, durable drain and debt

| Arm | Arrivals | Durable archive | Arrival/s | Archive/s | Surplus/s | Start debt | Peak debt | End debt | Debt slope records/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 155496 | 156288 | 972.777276 | 977.731999 | 4.954723 | 792 | 5688 | 0 | -11.877537 |
| treatment | 156288 | 156552 | 977.745448 | 979.397045 | 1.651597 | 1056 | 6104 | 792 | -6.282128 |

The census uses current durable cohorts/counters in one read snapshot. Rates use actual measured snapshot elapsed: CONTROL 159.847484 s, TREATMENT 159.845285 s. Fixed source offsets are identical; acquisition gaps are reported separately. The hot-debt slope is least-squares across fixed endpoints and live periodic samples within the declared interval. CONTROL archive drain strictly exceeded arrivals, its debt discharged, and no relevant capacity/deadline failure occurred. None of the three required reproduction conditions held. Treatment also has positive archive surplus and debt reduction; this does not overcome invalid control reproduction.

| Arm | Archive durable slices, whole arm | Durable slice records, whole arm | Min/max records per slice | Contract cap |
| --- | --- | --- | --- | --- |
| control | 438 | 176088 | 56/512 | 512 |
| treatment | 451 | 176616 | 56/512 | 512 |

All actual worker dispatch/execution/delay/ready/pending cycles, slice records, native needs/readiness/effective deadlines, feasible-side reconstruction, selected side/refusal and peer reservation state are retained in the raw archive-cycles, native-turns, source-queues and timeline.

## 7. Mature retirement and every native scope

| Arm | Scope | Eligible arrivals | Archive | Retired | Pending start | Pending peak | Pending end | Retirement excess start/end | Keeps pace |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | meteora | 75392 | 75776 | 75648 | 256 | 3464 | 384 | 0/0 | False |
| control | pump | 30039 | 30192 | 30141 | 102 | 1326 | 153 | 0/0 | False |
| control | pumpswap | 50065 | 50320 | 50235 | 170 | 2210 | 255 | 0/0 | False |
| treatment | meteora | 75776 | 75904 | 75776 | 0 | 2176 | 128 | 0/0 | False |
| treatment | pump | 30192 | 30243 | 30192 | 0 | 324 | 51 | 0/0 | False |
| treatment | pumpswap | 50320 | 50405 | 50320 | 0 | 1421 | 85 | 0/0 | False |

Pump, PumpSwap and Meteora are the only active native record scopes in this driver. Every scope received durable retirement service; none was silently starved. Nevertheless, each arm retired **264 fewer records** than it newly archived over the fixed mature window. CONTROL pending debt rose 528→792; TREATMENT rose 0→264. All per-scope strict keep-pace/nonincreasing-pending criteria fail. Recovery excess resolved, but that is insufficient to certify retirement sustainability. The window is not shifted to find a passing queue phase.

| Arm | Scope | Archive arrivals/s | Archive/s | Archive surplus/s | Retirement/s | Hot start/peak/end | Hot slope |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | meteora | 471.649589 | 474.051878 | 2.402290 | 473.251115 | 384/2680/0 | -5.466989 |
| control | pump | 187.922883 | 188.880045 | 0.957162 | 188.560991 | 153/1173/0 | -2.386424 |
| control | pumpswap | 313.204805 | 314.800076 | 1.595271 | 314.268319 | 255/1955/0 | -4.024124 |
| treatment | meteora | 474.058399 | 474.859173 | 0.800774 | 474.058399 | 512/2816/384 | -2.608915 |
| treatment | pump | 188.882643 | 189.201702 | 0.319059 | 188.882643 | 204/1122/153 | -1.210225 |
| treatment | pumpswap | 314.804406 | 315.336170 | 0.531764 | 314.804406 | 340/2166/255 | -2.462988 |

## 8. Every original recovery episode and deadline

All **91** episodes are retained separately by scope/side/original deadline/original wall start: **57 CONTROL**, **34 TREATMENT**. Required deadline observations (origin source ≤240 s): **19 CONTROL**, **17 TREATMENT**. All observed episodes passed before their own original deadlines; OPEN/CENSORED/FAILED counts are zero. Late-origin episodes receive credit only for directly observed pre-deadline resolution. No replacement/re-enrollment/rebased origin substitutes for an older episode. Exact clocks, opening excess, durable progress, resolution and headroom: [RECOVERY_EPISODES.json](RECOVERY_EPISODES.json).

Source start/deadline below are offsets from each immutable Wire.start. Resolution is the directly recorded monotonic clock; exact original wall starts and clock projection are in JSON. Durably committed record progress is scoped to the original episode, not a later replacement.

| Arm | Scope | Side | Original source start s | Original source deadline s | Opening excess | Durable progress | Resolution monotonic | Headroom s | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | meteora | archive | 181.069115 | 301.069115 | 24 | 512 | 2748.827114 | 115.680676 | PASS |
| control | meteora | archive | 191.069115 | 311.069115 | 24 | 512 | 2759.077196 | 115.430594 | PASS |
| control | meteora | archive | 192.069115 | 312.069115 | 24 | 456 | 2759.934161 | 115.573629 | PASS |
| control | meteora | archive | 208.069115 | 328.069115 | 24 | 512 | 2776.091611 | 115.416179 | PASS |
| control | meteora | archive | 209.069115 | 329.069115 | 24 | 456 | 2776.683969 | 115.823821 | PASS |
| control | meteora | archive | 215.069115 | 335.069115 | 24 | 512 | 2786.677704 | 111.830086 | PASS |
| control | meteora | archive | 218.069115 | 338.069115 | 408 | 17024 | 2828.125460 | 73.382330 | PASS |
| control | pumpswap | archive | 219.069115 | 339.069115 | 275 | 9095 | 2822.493070 | 80.014720 | PASS |
| control | meteora | retirement | 221.069115 | 341.069115 | 24 | 10496 | 2817.165758 | 87.342032 | PASS |
| control | pumpswap | retirement | 225.069115 | 345.069115 | 275 | 2304 | 2804.779118 | 103.728672 | PASS |
| control | pump | archive | 228.069115 | 348.069115 | 10 | 41 | 2800.291529 | 111.216261 | PASS |
| control | pump | retirement | 228.069115 | 348.069115 | 71 | 768 | 2803.068753 | 108.439037 | PASS |
| control | pump | archive | 229.069115 | 349.069115 | 122 | 340 | 2802.372760 | 110.135030 | PASS |
| control | pump | archive | 232.069115 | 352.069115 | 122 | 153 | 2803.488356 | 112.019434 | PASS |
| control | pump | archive | 233.069115 | 353.069115 | 173 | 765 | 2807.428139 | 109.079651 | PASS |
| control | pumpswap | retirement | 235.069115 | 355.069115 | 181 | 768 | 2806.338494 | 112.169296 | PASS |
| control | pump | archive | 237.069115 | 357.069115 | 122 | 204 | 2808.309312 | 112.198477 | PASS |
| control | pump | archive | 238.069115 | 358.069115 | 122 | 357 | 2810.475232 | 111.032557 | PASS |
| control | pumpswap | retirement | 238.069115 | 358.069115 | 92 | 512 | 2808.810946 | 112.696844 | PASS |
| control | pump | archive | 241.069115 | 361.069115 | 122 | 204 | 2811.483076 | 113.024714 | PASS |
| control | pump | archive | 242.069115 | 362.069115 | 122 | 204 | 2812.158962 | 113.348828 | PASS |
| control | pump | archive | 243.069115 | 363.069115 | 122 | 153 | 2812.897654 | 113.610136 | PASS |
| control | pumpswap | retirement | 245.069115 | 365.069115 | 101 | 256 | 2814.458009 | 114.049781 | PASS |
| control | pump | archive | 246.069115 | 366.069115 | 98 | 129 | 2815.929892 | 113.577898 | PASS |
| control | pump | archive | 248.069115 | 368.069115 | 69 | 100 | 2816.877848 | 114.629942 | PASS |
| control | pump | archive | 248.069115 | 368.069115 | 74 | 156 | 2817.958952 | 113.548838 | PASS |
| control | meteora | retirement | 249.069115 | 369.069115 | 280 | 768 | 2818.478875 | 114.028915 | PASS |
| control | meteora | retirement | 250.069115 | 370.069115 | 24 | 768 | 2819.865119 | 113.642671 | PASS |
| control | pumpswap | retirement | 251.069115 | 371.069115 | 19 | 256 | 2820.680734 | 113.827056 | PASS |
| control | meteora | retirement | 252.069115 | 372.069115 | 280 | 768 | 2821.379289 | 114.128501 | PASS |
| control | pumpswap | retirement | 252.069115 | 372.069115 | 103 | 1024 | 2822.717357 | 112.790433 | PASS |
| control | meteora | retirement | 253.069115 | 373.069115 | 152 | 1024 | 2823.236418 | 113.271372 | PASS |
| control | pumpswap | archive | 254.069115 | 374.069115 | 275 | 340 | 2823.461501 | 114.046289 | PASS |
| control | meteora | retirement | 255.069115 | 375.069115 | 24 | 768 | 2824.207213 | 114.300577 | PASS |
| control | pumpswap | retirement | 255.069115 | 375.069115 | 14 | 512 | 2823.723710 | 114.784080 | PASS |
| control | pumpswap | archive | 255.069115 | 375.069115 | 275 | 340 | 2824.421365 | 114.086425 | PASS |
| control | pumpswap | archive | 256.069115 | 376.069115 | 190 | 255 | 2825.318906 | 114.188884 | PASS |
| control | meteora | retirement | 257.069115 | 377.069115 | 24 | 768 | 2825.813586 | 114.694204 | PASS |
| control | pumpswap | archive | 258.069115 | 378.069115 | 199 | 264 | 2826.017786 | 115.490004 | PASS |
| control | pumpswap | retirement | 258.069115 | 378.069115 | 181 | 512 | 2826.246928 | 115.260862 | PASS |
| control | meteora | retirement | 259.069115 | 379.069115 | 280 | 768 | 2827.060989 | 115.446800 | PASS |
| control | pumpswap | archive | 259.069115 | 379.069115 | 255 | 320 | 2827.253898 | 115.253892 | PASS |
| control | pumpswap | retirement | 259.069115 | 379.069115 | 9 | 256 | 2827.707625 | 114.800165 | PASS |
| control | pumpswap | archive | 260.069115 | 380.069115 | 47 | 112 | 2827.908029 | 115.599761 | PASS |
| control | meteora | retirement | 260.069115 | 380.069115 | 280 | 768 | 2828.448667 | 115.059123 | PASS |
| control | pumpswap | retirement | 260.069115 | 380.069115 | 8 | 1024 | 2830.357996 | 113.149794 | PASS |
| control | meteora | archive | 261.069115 | 381.069115 | 64 | 168 | 2828.860311 | 115.647478 | PASS |
| control | meteora | retirement | 261.069115 | 381.069115 | 152 | 1000 | 2829.584681 | 114.923109 | PASS |
| control | meteora | archive | 262.069115 | 382.069115 | 120 | 592 | 2830.392954 | 115.114836 | PASS |
| control | meteora | archive | 263.069115 | 383.069115 | 24 | 440 | 2831.165828 | 115.341962 | PASS |
| control | pumpswap | retirement | 263.069115 | 383.069115 | 174 | 768 | 2831.116373 | 115.391417 | PASS |
| control | meteora | archive | 272.069115 | 392.069115 | 24 | 512 | 2840.154892 | 115.352898 | PASS |
| control | meteora | archive | 273.069115 | 393.069115 | 24 | 456 | 2840.868209 | 115.639581 | PASS |
| control | meteora | archive | 316.069115 | 436.069115 | 24 | 512 | 2884.141508 | 115.366282 | PASS |
| control | meteora | archive | 317.069115 | 437.069115 | 24 | 456 | 2884.659514 | 115.848276 | PASS |
| control | meteora | retirement | 317.069115 | 437.069115 | 24 | 768 | 2885.167983 | 115.339806 | PASS |
| control | meteora | archive | 323.069115 | 443.069115 | 24 | 512 | 2891.154574 | 115.353216 | PASS |
| treatment | meteora | archive | 194.570623 | 314.570623 | 24 | 512 | 3530.112324 | 115.395466 | PASS |
| treatment | meteora | archive | 195.570623 | 315.570623 | 24 | 456 | 3530.887939 | 115.619851 | PASS |
| treatment | meteora | archive | 211.570623 | 331.570623 | 24 | 512 | 3547.353862 | 115.153928 | PASS |
| treatment | meteora | archive | 212.570623 | 332.570623 | 24 | 456 | 3547.975763 | 115.532027 | PASS |
| treatment | meteora | archive | 215.570623 | 335.570623 | 24 | 512 | 3553.806962 | 112.700828 | PASS |
| treatment | meteora | archive | 217.570623 | 337.570623 | 408 | 10880 | 3582.462469 | 86.045321 | PASS |
| treatment | pumpswap | archive | 218.570623 | 338.570623 | 275 | 284 | 3561.368434 | 108.139356 | PASS |
| treatment | meteora | retirement | 221.570623 | 341.570623 | 24 | 7680 | 3578.528427 | 93.979363 | PASS |
| treatment | pumpswap | archive | 221.570623 | 341.570623 | 190 | 5610 | 3579.445799 | 93.061991 | PASS |
| treatment | pump | archive | 226.570623 | 346.570623 | 26 | 1026 | 3571.313487 | 106.194303 | PASS |
| treatment | pumpswap | retirement | 231.570623 | 351.570623 | 186 | 256 | 3570.396353 | 112.111437 | PASS |
| treatment | pumpswap | retirement | 232.570623 | 352.570623 | 270 | 1280 | 3573.570849 | 109.936941 | PASS |
| treatment | pump | archive | 233.570623 | 353.570623 | 122 | 204 | 3572.200413 | 112.307377 | PASS |
| treatment | pump | archive | 234.570623 | 354.570623 | 122 | 204 | 3572.855839 | 112.651951 | PASS |
| treatment | pump | archive | 235.570623 | 355.570623 | 122 | 153 | 3573.792770 | 112.715020 | PASS |
| treatment | pumpswap | retirement | 236.570623 | 356.570623 | 10 | 1280 | 3576.892574 | 110.615216 | PASS |
| treatment | pumpswap | retirement | 239.570623 | 359.570623 | 90 | 1536 | 3581.118422 | 109.389368 | PASS |
| treatment | meteora | retirement | 241.570623 | 361.570623 | 24 | 768 | 3579.719125 | 112.788666 | PASS |
| treatment | pumpswap | archive | 242.570623 | 362.570623 | 275 | 316 | 3580.363007 | 113.144783 | PASS |
| treatment | meteora | retirement | 243.570623 | 363.570623 | 152 | 768 | 3580.633742 | 113.874048 | PASS |
| treatment | pumpswap | archive | 244.570623 | 364.570623 | 299 | 619 | 3582.198388 | 113.309402 | PASS |
| treatment | pumpswap | retirement | 244.570623 | 364.570623 | 169 | 512 | 3581.997136 | 113.510654 | PASS |
| treatment | meteora | retirement | 246.570623 | 366.570623 | 24 | 768 | 3582.757140 | 114.750650 | PASS |
| treatment | meteora | archive | 246.570623 | 366.570623 | 408 | 1576 | 3585.462985 | 112.044805 | PASS |
| treatment | pumpswap | archive | 246.570623 | 366.570623 | 275 | 340 | 3582.972782 | 114.535009 | PASS |
| treatment | pumpswap | retirement | 246.570623 | 366.570623 | 337 | 2304 | 3587.737508 | 109.770282 | PASS |
| treatment | pumpswap | archive | 247.570623 | 367.570623 | 275 | 340 | 3584.106918 | 114.400873 | PASS |
| treatment | pumpswap | archive | 248.570623 | 368.570623 | 275 | 595 | 3585.476200 | 114.031590 | PASS |
| treatment | meteora | archive | 249.570623 | 369.570623 | 240 | 344 | 3585.949362 | 114.558428 | PASS |
| treatment | meteora | archive | 252.570623 | 372.570623 | 24 | 264 | 3587.940536 | 115.567254 | PASS |
| treatment | pumpswap | retirement | 254.570623 | 374.570623 | 327 | 512 | 3590.351438 | 115.156352 | PASS |
| treatment | pumpswap | retirement | 255.570623 | 375.570623 | 70 | 1000 | 3591.373365 | 115.134425 | PASS |
| treatment | meteora | archive | 323.570623 | 443.570623 | 24 | 512 | 3658.886782 | 115.621008 | PASS |
| treatment | meteora | retirement | 325.570623 | 445.570623 | 24 | 1000 | 3660.283939 | 116.223851 | PASS |

## 9. Coupled balances and no debt export

Independent native ingested counters reconcile with total hot + archived-pending + durable retired in every read snapshot. The eligible arrival census is eligible hot + archived-pending + durable retired; this census identity is definitional, while the native ingested balance and interval archive/retirement flows independently reconcile. Pins and gaps were zero, so no preservation exception invalidates eligibility.

| Arm | Eligible hot start/end | Archived-pending start/end | Retired during interval | Hot delta | Pending delta | Coupled residuals |
| --- | --- | --- | --- | --- | --- | --- |
| control | 792/0 | 528/792 | 156024 | -792 | 264 | 0 for every scope |
| treatment | 1056/792 | 0/264 | 156288 | -264 | 264 | 0 for every scope |

TREATMENT hot debt fell by exactly 264 while archived-pending rose by 264. Thus its endpoint hot-debt reduction is entirely matched by retirement debt transfer, even though substantial work was durably retired. It does not prove net maintenance-debt reduction. CONTROL combined hot+pending debt fell 1,320→792. No hidden record balance or source backlog is erased to create a pass.

## 10. A2 offers, placements, progress and deadline correlation

| Arm | Offers | Accepted | Timeouts | Bypasses incl. ACK | Actual before-source placements | Affected frames | Placements with direct durable records |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| treatment | 22 | 21 | 0 | 1275 | 21 | 22 | 1 |

CONTROL **A2 opportunity count = 0**. TREATMENT opened 22 offers: 21 accepted, one bypassed due to an intervening owner queue, zero timeouts/overshoots. Its 1,275 bypass counters include one protocol ACK; 1,274 are pre-source bypasses. Reasons: no-positive-hint 682, maintenance-unfinished 590, checkpoint-handoff 1, owner-queue 1, head-ACK 1. Accepted owner admission alone is not claimed as durable service. Twenty-one actual maintenance-owner entries preceded their source-owner entries. One directly committed **56 PumpSwap archive records**; the other placements had no direct record credit.

[A2_PLACEMENTS.json](A2_PLACEMENTS.json) contains all 21 placements, native durable progress/records, selected side, fresh scope debt, next native-observation debt changes and the headroom of every then-active original recovery episode. The next observation can include intervening source arrivals or other maintenance, so those changes are temporal correlation only. No causal benefit beyond this pair is claimed.

| Maintenance sequence | Source sequence | Selected side | Durable records | Gate wait s | Original recovery headroom(s) |
| --- | --- | --- | --- | --- | --- |
| 1528 | 1529 | none | 0 | 0.000324 | no active episode |
| 1543 | 1544 | none | 0 | 0.000981 | no active episode |
| 1592 | 1593 | none | 0 | 0.000198 | no active episode |
| 1633 | 1634 | none | 0 | 0.000360 | no active episode |
| 1673 | 1674 | archive | 56 | 0.000295 | no active episode |
| 1697 | 1698 | none | 0 | 0.000391 | no active episode |
| 1835 | 1836 | none | 0 | 0.000239 | no active episode |
| 2727 | 2728 | none | 0 | 0.000234 | no active episode |
| 2755 | 2756 | none | 0 | 0.000196 | no active episode |
| 2859 | 2860 | none | 0 | 0.000208 | no active episode |
| 3126 | 3127 | none | 0 | 0.000190 | no active episode |
| 3233 | 3234 | none | 0 | 0.000368 | no active episode |
| 3272 | 3273 | none | 0 | 0.000208 | no active episode |
| 3290 | 3291 | none | 0 | 0.000250 | no active episode |
| 3333 | 3334 | none | 0 | 0.000254 | no active episode |
| 3476 | 3477 | none | 0 | 0.000220 | no active episode |
| 3520 | 3521 | none | 0 | 0.000306 | no active episode |
| 3579 | 3580 | none | 0 | 0.000270 | no active episode |
| 3628 | 3629 | none | 0 | 0.000364 | no active episode |
| 3730 | 3731 | none | 0 | 0.000347 | no active episode |
| 3880 | 3881 | none | 0 | 0.000231 | no active episode |

## 11. Housekeeping/M1 constant proof, fairness and continuity

Full exact diff/AST proof preserves all M1 completion/cooperative logic, housekeeping ordering/prefix context, retention/floors/continuity, native arbiter, reservation rules and generation fencing. Protected file hashes are in STATIC_CONTROL_PROOF.json; no treatment byte was modified. Native prefix trigger counts can differ with legal scheduling while the formula/semantics remain exact.

| Arm | Housekeeping demand peak | Prefix triggers | Prefix commits | Prefix units | All housekeeping units | Prefix source/urgent returns | All retention source/urgent returns |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | 2 | 1 | 1 | 1031 | 6018 | 1/0 | 216/10 |
| treatment | 2 | 0 | 0 | 0 | 6062 | 0/0 | 226/8 |

CONTROL’s single native prefix committed 1,031 housekeeping units, zero record retirement, then returned to source with the prepared receipt still pending. TREATMENT needed no prefix. Both kept the identical bounded native GC and M1 durable-completion accounting.

| Arm | Owner admissions | Priority 0 admissions | Owner queue peak delay s | FIFO errors | Unresolved accepted futures |
| --- | --- | --- | --- | --- | --- |
| control | 3889 | 370 | 0.984254 | 0 | 0 |
| treatment | 3980 | 369 | 0.753223 | 0 | 0 |

Native strict urgent priority and nonurgent FIFO after admission remain byte-identical. No observed FIFO error, urgent/candidate error or native arbiter refusal/failure occurred. Original leases, two-sided reservations, worker lease, generation fencing and transaction bounds were exercised unchanged. Actual per-scope service gaps and all checkpoint holds are retained in RESULTS.json/raw owner events. Every scope advanced retirement/continuity floors; no active gap or pin remained. Floor and continuity counts at both mature endpoints and whole-arm end are in RESULTS.json.

## 12. Ages, resource bounds, checkpoint and integrity

| Arm | Hot age peak s | Retained age peak s | Source lag peak s | DB+WAL peak bytes | RSS peak KiB | SQLite integrity |
| --- | --- | --- | --- | --- | --- | --- |
| control | 185.298375 | 192.283310 | 8.198793 | 1031137944 | 452780 | ok |
| treatment | 186.726328 | 190.726328 | 8.692260 | 1029879456 | 484128 | ok |

Both residence peaks are strictly <240 s; no equality is passed. DB+WAL stayed below 2 GiB. Worker/process groups exited, owner threads stopped, accepted owner futures unresolved=0, and writer transaction state at close was false. All returned native owner operations have their transaction state recorded. Two independent native spawned workers per arm exited; no process-group leak or abandoned transaction was observed.

| Arm | Checkpoint calls | Reclaimed | Boundary calls | Boundary reclaimed | Incomplete receipts | Worker/process leaks |
| --- | --- | --- | --- | --- | --- | --- |
| control | 297 | 291 | 119 | 118 | 2 | 0 |
| treatment | 299 | 297 | 123 | 123 | 0 | 0 |

Transient incomplete checkpoint receipts are retained as such, not fabricated completion. Native successful reclamations and bounded checkpoint handoffs continued in both arms. No new terminal refusal replaced a historical maintenance failure.

## 13. Observation cost, errors and measurement gaps

| Recorded elapsed timer, seconds | CONTROL | TREATMENT |
| --- | --- | --- |
| diagnostic_wrapper | 0.629381 | 0.660196 |
| periodic_observer_total | 1.053335 | 1.102106 |
| persistence | 0.020822 | 0.011164 |
| screen_boundary_observation | 0.055018 | 0.056985 |
| screen_queue_observation | 4.607556 | 4.403526 |
| serialization | 0.018817 | 0.022984 |

Recorded timer sums: CONTROL 6.384928 s; TREATMENT 6.256960 s. Timers overlap, including scheduled-boundary capture within observer timers; this is not an isolated overhead ratio or a <1% benchmark. Spawned-child startup observation elapsed is separately retained. All observation costs remain in measured runtime; nothing is subtracted.

| Arm | Dropped samples | Observer/errors | Max periodic gap s | Start/end acquisition gap s | Configuration/bytes |
| --- | --- | --- | --- | --- | --- |
| control | 0 | 0 | 5.041411 | 0.006815/0.014298 | identical, predeclared |
| treatment | 0 | 0 | 5.069475 | 0.008442/0.013727 | identical, predeclared |

All gaps stayed within predeclared bounds (boundary ≤1 s, periodic ≤10 s), with zero observer error/drop. Native rolling-ring evictions are reported separately from full-capture drops. Full event capture preserved source queues, A2 offers/placements, original episode transitions and native decisions. No material capture asymmetry was found.

## 14. Whole-arm totals, provider firewall and exact verdict

| Arm | Scope | Ingested | Archived durable | Retired durable | Hot retained | Archived-pending retained |
| --- | --- | --- | --- | --- | --- | --- |
| control | meteora | 170752 | 85376 | 85248 | 85376 | 128 |
| control | pump | 68034 | 34017 | 33864 | 34017 | 153 |
| control | pumpswap | 113390 | 56695 | 56440 | 56695 | 255 |
| treatment | meteora | 170752 | 85632 | 85504 | 85120 | 128 |
| treatment | pump | 68034 | 34119 | 34068 | 33915 | 51 |
| treatment | pumpswap | 113390 | 56865 | 56780 | 56525 | 85 |

These whole-arm counters include integrity teardown and are reported separately; they do not change the mature-window verdict. Provider **calls=0, attempts=0** in both arms. Parent and spawned-worker Internet firewalls preserved native Unix IPC and recorded attempts before packet emission. There was no credential, wallet or signing authority in the child environment.

| Predeclared requirement | CONTROL | TREATMENT |
| --- | --- | --- |
| archive_positive_surplus_and_debt_reduction | True | True |
| conservation_reconciles | True | True |
| control_reproduces | False | False |
| hot_debt_reduction_not_only_exported | True | False |
| integrity_resources | True | True |
| observation_valid | True | True |
| original_deadlines_pass | True | True |
| retirement_sustainable_every_scope | False | False |
| safety_fairness | True | True |
| source_integrity_no_upstream_masking | True | True |

Under the fixed precedence, valid observation plus failure to reproduce CONTROL’s required archive deficit/debt/recovery condition yields **INCONCLUSIVE_CONTROL_DID_NOT_REPRODUCE**. Treatment’s archive surplus/debt decrease and observed A2 placement do not alter that classification. Retirement keep-pace/no-export requirements also remain unproven/failed in the declared interval. There is no capacity green, causal capacity-recovery claim, Stage E promotion or Stage F authority. [RESULTS.json](RESULTS.json) contains the complete current-run measurements and mechanical decision; all raw inputs were preserved before interpretation. **STOP FOR ASTRA.**
