# Actual original and add performance

`runtime/component_performance.py` reports actual native booked events. The
original purchase and the one native add retain their own quantities, booked
costs and event times. Partial and final sales retain actual quantities, native
basis releases, net proceeds and native lifecycle/event identities. The ledger
continues to own every financial total.

The analytical convention is `pooled-native-basis-pro-rata-integer-v1`:

1. Allocate sold quantity in proportion to the components' remaining quantities.
2. Allocate the **native booked** basis release in proportion to their remaining
   basis allocations.
3. Allocate the **native net** proceeds in proportion to the sold quantities.

Each division floors the original component allocation and assigns the integer
remainder to the add. Quantity and basis allocations cannot exceed the respective
remaining quantity/basis. Final settlement consumes all remaining allocations.
These allocations conserve native quantity, remaining basis and realized P&L at
each event. Because native basis is pooled and rounded, an intermediate component
can have zero quantity and a nonzero remaining basis allocation; that allocation
is reported explicitly and released at a later native sale/settlement. Execution
costs included in booked cost or net proceeds are not deducted again.

This is actual component attribution. It does not calculate hypothetical no-add
performance or causal profit from scaling. Realized P&L excludes unrealized marks;
component unrealized marks are unavailable in this projection. Existing observed
high-water/mark facts remain observations, separate from execution events.

Pons Current collects the report through a read-only native adapter into its
existing completed-lifecycle rows and compact result. Existing Pons journal
compaction preserves the incremental component prefix before removing journal
detail. Pump Current and Pump/Pons Survivor use their existing preserved native
PaperBook retention pass: the same already-verified event iteration preserves
component facts in the native prefix and existing terminal learning facts. No
protective-event replay, extra journal writer, provider acquisition, accounting
owner, or storage framework is introduced.

Reports with missing originals, retired component detail, failed exact joins or
incomplete native deltas keep authoritative totals and mark the split unavailable.
Native reports use integer native quote/token units. The shared-capital export
does not contain exact native component events; its split is explicitly unavailable
and its authoritative USD totals remain separate. No conversion is inferred from
staged-add USD basis.

Completed collectors and retirement prefixes report available/unavailable coverage,
including known missing older records. Retirement coverage describes capture at
that boundary. Compact aggregate original/add totals remain in the existing folded
prefix after individual bounded learning records disappear; missing captured splits
are excluded from those component aggregates and included in the coverage counts.
Older PaperBook folded state may lack the
count of retired never-filled cancellations; that historical count is explicitly
unavailable. The bounded learning store labels its facts selectively retained and
does not present them as the entire trade population. Native total coverage and
component detail coverage are separate.
