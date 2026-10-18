# Paused source-only bridge sketch

This branch is an unfinished checkpoint, not an integrated capability. The new
`runtime/pons_source_membership.py` module is **unwired and untested**. No native
producer, Plane observer, factory replay or public runner instantiates it. It
must not be selected, used as a proof or called a validated source bridge.

Root paused this work for actual EA run 39095028426 cost attribution (collect
39096145557). The preserved base is future c103 plus the reviewed Pons stage and
factory components; the two Current/Survivor integration conflicts were checked
by the future integration owner. Existing frozen 33288 remains separate.

Remaining implementation includes the real producer/true-COMMIT hooks, retention
and source-change invalidation, independent expected membership traversal,
idempotent native disposition hashes, fixed metadata shape/bounds, and genuine
rollback/commit-failure/missing-hook tests. Plane hooks must fan out the same
original native outer-COMMIT outcome alongside NativeCommitMeasurement. Raw
scout variants cannot become canonical economic events or imply held or consumer
closure. This module contains no database/provider call or financial authority.
