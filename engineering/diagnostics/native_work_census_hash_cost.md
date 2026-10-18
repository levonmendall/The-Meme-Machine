# Sealed native work census verification cost

`NativeWorkCohorts._finish` previously sorted and hashed the entire sealed
expected population after every outcome, including outcomes that could not yet
close the population. A 5,000-member native input batch therefore repeated a
5,000-member census hash roughly 5,000 times. This was observation work, with no
economic or service credit.

The incomplete cardinality and pending-disposition checks now precede that full
hash. A changed sealed member count still refuses immediately; the exact full
membership count/hash is verified before any closure. The public `expect` API
continues to reject changes or expansions after sealing. No SQL, transaction,
provider, strategy, clock, receipt, outcome or sampling contract changes.

The deterministic regression seals 128 members, traps census hashing during
127 incomplete callbacks, and requires the complete hash on the final callback.
A separate same-cardinality retained-member corruption must produce UNKNOWN
without closure. This proves the avoided repeated work and retained final
verification without a timing threshold.

The local 41-case pre-change bundle took 31.552s and the later 42-case bundle
took 7.298s. Their test populations differ by the new regression, so these are
diagnostic receipts, not an exact matched performance experiment. The final
private Current comparison separately measures the actual same native input
workload with and without observation; see `pump_current_input_prefix.md`.

This change does not solve the common reducer's 8,192-seen-cohort lifetime
limit. Continuous release still requires monotonic native window identities,
bounded replay detection, cumulative chains, and retained unresolved work;
resetting or discarding old debt is not an acceptable rotation mechanism.
