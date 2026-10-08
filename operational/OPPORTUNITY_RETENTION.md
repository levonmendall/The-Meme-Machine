# Opportunity evidence retention

Opportunity telemetry has no strategy, execution, capital or recovery authority.
Native lifecycle journals and the shared Portfolio remain the economic sources.

The telemetry journal retains 4,096 rows and a checksum-verified prefix containing
the preceding chain hash, event counts and the latest retired observation time.
Each retirement slice processes at most 512 rows. Existing larger journals drain
in those slices without changing their epoch, native state or cumulative counts.
The journal body bound is 65,536 bytes. Pending outcome targets retain at most
1,024 rows; retired unobserved targets are counted explicitly. Orphan scan cursors
are deleted in bounded slices. Existing legacy receipts and links have their own
10,000-row retention, preserving links for active native exposure.

A prefix retains chain identity and counts; it does not preserve discarded market
observations. An outcome interval overlapping discarded evidence reports
`RETAINED_EVIDENCE_INCOMPLETE` and null excursion/return measurements. Retention
does not turn missing evidence into complete outcomes or strategy rejection.
Interrupted retirement rolls back the prefix, deletions and immutable trigger
together. The old schema needs no destructive migration: the prefix is additive
metadata in the existing store.

The required future right-tail capture audit remains required. It must state the
scope and completeness of its source observations; a retained telemetry prefix
cannot prove an unobserved underlying price path. This change performs no such
strategic audit and grants no exception to its mandate.
