# Idle-Capital Rotation — future capital-governor contract

This is a design contract for later implementation only.

## Authority boundary

A future `PortfolioCapitalGovernor` (name illustrative) must sit above lane reservation requests and below the canonical shared portfolio accountant. It must not import strategy alpha logic.

Its inputs are:

- reconciled portfolio/lane capital state;
- a lane's already-qualified reservation request;
- frozen lease/risk limits;
- deterministic priority inputs.

Its output is either:

- no lease;
- a bounded lease grant tied to one reservation request.

## Durable lease journal

Lease state must be append-only and hash chained, or represented directly as canonical portfolio events with equivalent replay guarantees.

Required states:

`requested -> granted -> attached_to_reservation -> deployed -> return_pending -> returned`

with `cancelled` allowed before deployment.

## Serialization

Two borrowers cannot consume the same funding-owner capital. The same single-writer/transaction boundary that protects portfolio reservations must serialize lease grants.

## Home-lane protection

The funding owner retains a frozen protected reserve. A lease may use only capital above that reserve and never capital already reserved/deployed.

A later home-lane opportunity cannot revoke deployed borrower basis. It may block renewal/new leases and recall still-uncommitted grants.

## Attribution

Implementation must keep separate fields for:

- capital funding owner;
- strategy economic owner;
- portfolio economic result.

No attribution formula is selected here. Before activation, a separate policy must define how lane-level return, profit factor, and drawdown are reported under leased capital without affecting exact portfolio P&L reconciliation.

## Recovery

After crash/restart, the governor must reconstruct every outstanding lease from durable facts and cross-check:

- funding-owner unavailable amount;
- borrower reservation/deployment;
- terminal return state.

Ambiguity fails closed. It may not assume a lease was returned because a process disappeared.

## Forbidden designs

- one unrestricted shared cash pool;
- lending open or reserved capital;
- borrowing against unrealized marks;
- recursive/re-lending chains;
- outcome-based borrower priority;
- lender-triggered forced liquidation of valid deployed positions;
- hidden cross-lane transfers outside canonical portfolio accounting;
- runtime implementation before utilization evidence and final E/F/G composition.
