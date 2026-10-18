# Pons private-owner caller integration

This caller component follows reviewed source `a35bf694` and the independently
reviewed two-file Pons helper `0dc1b3bbd06b4f0ea56e09fdb71ee2e00a220d11`.
It remains a future, unselected component. No application allowlist, root wire,
provider permission, financial guard or readiness predicate is opened.

When an actual private normal BootContext exists, Supervisor.start_lane('pons')
uses the fixed PonsOwnerLaunch helper. It binds the actual existing lane UUID
and Popen child through one inherited anonymous descriptor and the original
absolute fifteen-second handoff deadline. The descriptor and packet are not
environment readiness flags. No-capability launches retain the original CLI,
environment and subprocess path.

The actual lane entry consumes the Pons-only channel before its lock/provider/
native startup. It requires the CLI state root to equal the accepted context's
root before opening the lane lock. It rechecks the private context, original root acceptance
window and local stop immediately before provider install or native writers.
The process-private context is available to native consumers through the
helper's exact current_pons_owner_context API. It closes on normal return or
partial startup failure. This Pons identity is distinct from the Solana source
capability; it proves neither Pons canonical coverage nor financial protection.

The Supervisor retains the actual child and instance before binding. A failed
handoff invokes its original process-group stop/reap; if cleanup itself fails,
the original exception and child ownership remain available to the outer
Supervisor's original final cleanup. No abandoned successful owner registration
or positive funding readiness is emitted.

Verification with the original offline driver:

- Seven actual helper IPC/kernel acquisition cases plus five caller cases pass:
  12 tests in 6.220 seconds, `normal-pons-owner-caller-first-focused.log`.
- The original native startup module passes 11 tests in 0.191 seconds,
  `normal-pons-owner-caller-native-startup-focused.log`.
- Original stale-predecessor child health and funding-closed OBS admission cases
  pass in 0.174 seconds, `normal-pons-owner-caller-adjacent-focused.log`.
- After the independent CLI-root finding, all seven helper and six caller cases
  pass in 7.656 seconds, `normal-pons-owner-cli-root-focused.log`. The new case
  retains the foreign root's original contents, verifies no lane lock appears,
  and traps both provider and native constructors before entry.

Caller mocks test ordering and ownership only; they are not issuer capabilities.
The failed-handoff subprocess and original group stop/reap are real. Helper
acquisition simulates protected root/unit/native namespace inputs explicitly.
No actual systemd seal, AWS native market workload or one-hour acceptance is
established. One rejected command used a module name as a case and ran no tests;
the corrected module/case checks above passed.

This initial helper is one-shot and retains the original sealed acquisition
window. Same-Supervisor child replacement after that initial window, nonflat
restart and actual economic/protection population completion require their own
reviewed lifetime/recovery interfaces. An existing open PAPER position must not
be made flat to satisfy this initial boot scope. The source component's explicit
missing-economic-witness funding refusal stays in force.
