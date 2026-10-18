# Optional stalled-startup main-frame observation

This component investigates the missing main-thread frame in funding-closed
run 39085764934 (app 780f4015). That run's health thread continued after TERM,
but no Python signal observation was available before the original native join
deadline. The actual blocking operation remains unknown. This is a diagnostic,
not a cancellation repair or a capacity/readiness claim.

With the existing `MM_OPERATION_COST_DIAGNOSTICS=1`, the existing Pons health
thread may capture the main Python stack only while one of seven fixed original
startup operations is still active for at least five seconds. Capture is bounded
to eight fixed module/function/line frames, two per operation, fourteen per
process and one attempt per ten seconds. Fixed self `/proc` PID/main-TID start
identities bracket the capture. No locals, filenames, SQL, messages, provider
addresses or environment values are exported. An observed Python boundary does
not identify the native operation, SQL cause, signal delivery or lock ownership.

The normal signal handler, native SQL queries, query cancellation, transaction
boundaries, startup order, readiness and original 15/65-second joins are unchanged.
Actual Survivor factory, observation enrollment and initial warmup/discovery
checkpoint scopes are descriptive only. Optional failure produces no capture.
The combined collector retains a separately typed field with its original clock;
it does not re-label it as a cancellation stack. The original 1-MiB record and
64-KiB terminal reserves remain; only this optional field is discarded when
necessary to fit those original limits. It is not duplicated in descriptive
health.

Hosted regression 39088806332 found that the first implementation reused
`status.operation` for observation enrollment, so a normal provider callback saw
`native_operation='pons.observation_start'`. The original integrated assertion
correctly refused that scope leak. The diagnostic now preserves the original
three Pons restoration identifiers and native-operation projection unchanged.
The four additional stages use an independent diagnostic-only registry, with
at most eight active rows and no completed/public native-operation publication.
Registration is opt-in and nonblocking; the existing sampler still requires
that the exact row remain active across its frame capture. No new stage installs
or extends the read-only startup replay context. The Survivor factory retains
its existing replay scope, which ends before the normal Survivor step.

The original failed case passes unchanged in 0.195 seconds. Twelve startup-stack
cases pass in 9.758 seconds, covering all seven stage contracts, the four actual
wrapper call sites, diagnostic-off/overflow/lock contention, exception/cancellation
cleanup, owner-thread factory-versus-step replay lifetime and the original
native-SQL/deferred-TERM child. The hosted failure receipt remains preserved.
The full integrated-startup/native-startup group has 23 passes and one unchanged
Cloud clock-identity failure in 1.924 seconds. The latter reproduces using the
original dcefc1c2 test bytes and byte-identical provider-admission/provider-clock
sources: `/proc/self/ns/time` is unavailable. Its guard is preserved. A further
targeted test refuses a private trigger that completes during frame capture.

Initial focused validation: nine new FAST cases, including an actual disposable child
whose main thread executes a finite SQLite native query while the original
health thread publishes. TERM is sent after the first capture: later captures
can still show no Python signal/Event; the original query completes with its
exact result, the handler is subsequently observed, no progress handler was
installed, and health joins. This synthetic wait is not an AWS-cause attribution.
The initial failed test receipts remain under `/workspace/recovery-evidence`.

Adjacent native-startup/combined tests: 98 cases, 95 pass, two existing skips and
one Cloud nonroot access-test expectation failure. The latter reproduces using
the unchanged a92454bb diagnostic-access source: it rejects nonroot preparation
before reaching the expected parent-path rejection. No access guard was changed.
