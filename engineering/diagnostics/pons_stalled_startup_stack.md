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

Focused validation: nine new FAST cases, including an actual disposable child
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
