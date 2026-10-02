OBSERVER_V2:
INVALID_PAIR

PAPER ONLY. STOP FOR ASTRA. Stage E remains RED; Stage F remains NOT STARTED.

Trial 1, baseline, failed the bound workload/observation/receipt gate before the four-member cohort completed. One trial and one workload member started. Trials 2–6 were skipped and remain UNUSED. Retries: 0. Replacement trials: 0. Invalid pairs: 1. Complete valid pairs: 0. No overhead acceptance credit is earned.

The invalid attempt elapsed 109,542,723,996 ns (109.542723996 seconds). This duration is not a valid baseline. All measured helpers stopped; recorded benchmark provider attempts were zero. The aggregate `origins_valid` and `tape_valid` fields are false because the required complete cohort was not available; those fields alone do not identify a wrong import or changed tape. The measurement's `complete_members: 1` counts a returned member record, not successful completion of the required member frames. Detailed member failure and source progress are in the preserved raw archive.

The immutable candidate is S `7a516a6a92be9347661ac0e7f560971c171a0931`, T `9da7d1e1625ba04c1437c63606c90f5e293bdba7`, reviewed assembly `08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659`. All 1,241 reviewed source files and the original assembly manifest remained unchanged. Observer infrastructure and fresh environment metadata are external to the candidate assembly.

The job ran on runner ID 21, `the meme machine`, hostname `ubuntu-gd-2vcpu-8gb-nyc1`, DigitalOcean droplet 605465049. Target labels were `[self-hosted, linux, x64, meme-machine-stage-e-observer]`. Only this runner carries the observer label according to the user's Settings confirmation; the connected integration's runner-inventory API returned HTTP 403 requiring administration access. On-host inspection independently verified the runner identity, Ubuntu environment and enabled, active systemd service before preparation. The attached block volume was mounted at `/mnt/volume_nyc1_1790918115030` on `/dev/sda`, with approximately 47.79 GB free after tape preparation. The declared fixed member headroom was 12 GiB. The environment binding includes Python 3.12.14, its shared library, standard library and dependency files.

Successful preparation run [37019161849](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37019161849) verified the assembly, immutable tape, generator equivalence, semantic clock/bootstrap audit and baseline/observed differential proof before any trial or member started. All 240 native fixture frames matched exact payload bytes; only the finite generator index bound extended. The immutable 4,445-frame tape supplies the same 2,223-frame prefix to each combined member and all 4,445 frames to recovery. Semantic wall epoch 1800000000 and monotonic epoch 100 anchor at first source release and then advance at real speed. The decoder and archive share the native service's two spawn workers. Preparation probes released no workload source frames; their helpers terminated before readiness.

The observer workflow was pinned to `eb0446a2953d0e7107738268d96204994502734d`: one host, one job, timeout 720 minutes, immutable action pins, no matrix, no migration, no automatic rerun, and `cancel-in-progress: false`. A NEW executable declaration containing actual runner/job/run, environment, workflow, assembly, infrastructure, tape and proof identities was published and read back successfully before Trial 1. Its SHA-256 is `d332bf30eaa2cf53ebe6e025e8d47fcc408981a0bc766dc4ded979ea20e17d2e`; initial and final artifacts contain identical declaration bytes. The declared order was baseline → observed, observed → baseline, baseline → observed, with four members per trial and no warmups, retries or replacements.

No formal paired measurement exists: raw complete pairs are empty, and numerator, denominator and ratio are unavailable. The workflow stopped before formal native verification because the first cohort was invalid. A separate pure call to the exact S `certification.stage_e_native_v2.observer.verify()` rejected the honest incomplete record with `observer_raw_pairs_missing`. [NATIVE_VERIFIER_DIAGNOSTIC.json](NATIVE_VERIFIER_DIAGNOSTIC.json) records this rejection and the verifier source hash. It launched no workload, pressure replay, warmup, qualification or measurement, and confers no acceptance credit.

| Durable evidence | Identity |
| --- | --- |
| Observer run / job / attempt | [37021065563](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37021065563) / 110883973161 / 1 |
| Workflow terminal result | [RESULTS.json at a4fb375b6661637eda74acf17a5ebbc09f8ae06c](https://github.com/levonmendall/The-Meme-Machine/blob/a4fb375b6661637eda74acf17a5ebbc09f8ae06c/diagnostics/stage-e-observer-v2-self-hosted-execution/RESULTS.json) |
| Raw Trial 1 artifact | 11233586036; ZIP 261,917,655 bytes; SHA-256 `8cb1e6e7294feb2075918bd344e0f46f161e54b8afe5f088af81308c4455c6dc` |
| Raw `TRIAL-1.tar.gz` | 261,914,464 bytes; SHA-256 `6dfb54fb59b94fb6542d53a1227f36f18a3410bf95c8e67686cef57cc187cd0a` |
| Published durability receipt | [5e6faa3033334a664cbdcc490f860735fd8148f9](https://github.com/levonmendall/The-Meme-Machine/blob/5e6faa3033334a664cbdcc490f860735fd8148f9/diagnostics/stage-e-observer-v2-self-hosted-execution/TRIAL-1-DURABILITY.json); SHA-256 `aa5dac007c24575f540b5a6075da440662fecb6964a9bb400cd09f0597389475`; independently read back |
| Final metadata artifact | 11233356305; ZIP SHA-256 `6f87efbd96b8e8dbc38a94939027e04e9d3961152f06749297df90b11cc8b402`; downloaded and verified |
| Executable declaration artifact | 11233015767; ZIP SHA-256 `a7fdbb9d1132d94cbb95c26f814afb72166438d2c54d296c4f00eed354471e3d`; downloaded and verified |
| Successful preparation artifact | 11231713179; ZIP SHA-256 `2c4667ceba9408728f755594add367f9d55ee8422fa07408569e3db65d1c60dc`; downloaded and verified |

The workflow archived every raw trial file and checked its bytes/hash against [TRIAL_1_RAW_INVENTORY.json](TRIAL_1_RAW_INVENTORY.json) before upload. Upload started after the measured interval and helper termination. Artifact identity and the published durability receipt were verified before the terminal stop. The raw archive also remains at `/mnt/volume_nyc1_1790918115030/ov2/r37021065563/TRIAL-1.tar.gz`. Runtime databases are outside Git.

Local inspection of that 261.9 MB artifact was blocked by the execution tool's 32 MiB download limit; an authorized byte-range download returned HTTP 403. The exact member-level failure and source progress have therefore not been independently inspected here. No specific root cause is claimed. [EXECUTION_READBACK.json](EXECUTION_READBACK.json), [LEDGER.json](LEDGER.json), [STOP_FOR_ASTRA.json](STOP_FOR_ASTRA.json), and [ARTIFACT_HASHES.json](ARTIFACT_HASHES.json) bind the terminal metadata. Earlier targeting-stop and zero-start preparation records remain historical evidence, superseded by this terminal ledger.

The five unused slots do not authorize replacing the invalid pair. No tuning, retry, prepared qualification, canonical Stage E, promotion or Stage F followed the failure.

STOP FOR ASTRA.
