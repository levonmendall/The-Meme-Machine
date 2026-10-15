# Previous Render appearance with the shared $1,000 epoch

The appearance reference is deployed commit
`1deb19415ab1683f1fb6071ed6a1d6fdd5785817`, Render deployment
`dep-db5o97ajnfac73b63ej0` on the existing service
`srv-daqon53tqb8s73bdceq0`. This was the last working frontend before the
new-epoch cutover. The HTML shell and stylesheet are identical to that revision.
The overview again has six portfolio summary figures, two family cards, the
original three-chart row, tables, navigation and status layout.

Only Pump and Pons appear in family cards, charts, filters, comparisons and
operational tables. Current/Survivor reporting remains available. Public API
projection filters inactive family history before pagination; the canonical
reader retains every historical record and authentic portfolio total.

The additional allocation and performance panels have been removed from the
overview. Shared cash, realized-equity sizing, allocation references and native
position protection remain accessible inside existing-style disclosures on
System and position details. Capital and chart references come from the
authoritative snapshot, including exact presentation rounding. Current accounting
alone cannot label a stopped or unavailable PAPER service live.

No change is made to canonical accounting, snapshot validation/ingestion,
epoch isolation, inception/source pins, authentication, publisher, recovery,
provider settings, trading strategies, funding or service configuration.
The Render branch and inception-pinned command remain as already corrected by
the owner. Its expected trading candidate remains
`8782b263632d0163f07e93a6b1cffa5b94071e87`; the dashboard build identity is
independent of the trading source identity.

Focused validation: 65 dashboard/model/security tests, 31 shared-epoch tests,
17 snapshot-transport tests, plus eight-route frontend rendering and financial,
partial-position, stale-evidence and read-only checks. The actual initialized
`paper-shared-1000-20261011T071207Z` snapshot renders $1,000 starting/current
equity, zero positions/P&L and PAPER stopped; its chart reference is $1,000.
The historical $500 ledger digest remains
`3198aae1f3c732451f008c5a620b8f176792caf92c1517435675d9e04f3a4087`.
These checks make no market-provider requests or accounting mutations.

Reference stylesheet SHA-256:
`cc897350900fb0aeb6b4ba8c0f9e8b83bf8f1cce4bb0d32b1c733fe66d28fbb6`.
Reference HTML shell SHA-256:
`a08aedcacc16a0a72396175ccd184930ad4a0690bc52d79a4c9c9144414e8454`.
Source and rendered-component checks cover appearance restoration; a browser
pixel comparison has not been performed. Live deployment is accepted only after
Render serves these exact asset identities and the validated new-epoch API.
