# Idle-Capital Rotation Architecture v1 — isolated preparation

Status: **ARCHITECTURE ONLY — NOT ACTIVE**

Parent: `617f1b4ec2d6f3e1a8c79dd19c2a5b91549ed967`

This document stages a future design for improving capital utilization when one lane has genuinely idle capital and another lane has a qualified, executable opportunity.

It does **not** activate cross-sleeve borrowing.

## Why this is architecture-only

Capital rotation is materially different from a new signal or position-lifecycle feature. It changes portfolio-wide capital authority.

The existing prepared rule remains authoritative:

> **no cross-sleeve borrowing**

That rule stays in force unless a future lease design is parameterized from real utilization evidence, implemented against the final certified machinery, non-market certified, and explicitly promoted.

## Proposed model: bounded temporary capital leases

Capital never becomes an anonymous common pool.

A future lease would preserve two identities:

- **funding owner** — the sleeve whose reconciled available capital supplied the principal;
- **strategy owner** — the lane whose qualified strategy deploys it.

The lease temporarily grants reservation authority. It does not transfer permanent sleeve ownership.

## Capital that may never be leased

- deployed/open basis;
- active reservations;
- unrealized gains;
- capital required by a protected home-lane reserve;
- ambiguous or unreconciled capital.

Only canonical **available** capital may even be considered.

## Borrower rules

Borrowing cannot manufacture a trade.

The borrower must already have a normal policy-qualified opportunity and must pass all existing:

- freshness/finality;
- generation fencing;
- concentration;
- creator/distribution;
- turnover/depth;
- execution-stress;
- breadth/fill;
- position/lane exposure controls.

The lease is another upper bound, never a reason to enlarge past executable capacity.

## Recall behavior

The lender may eventually be allowed to recall **uncommitted** leased capital.

A lender cannot force-close a valid open borrower position merely because its own opportunity appeared. Deployed principal returns through normal borrower settlement or another future separately certified unwind rule.

This avoids turning capital governance into an uncontrolled exit strategy.

## Accounting model

The common portfolio accountant must be the sole cross-lane cash authority.

Every lease requires durable provenance for:

- portfolio epoch;
- funding-owner lane;
- strategy-owner lane;
- amount;
- request/grant identities;
- attached reservation/lifecycle;
- policy/risk identities;
- return/settlement identity.

Native lane ledgers may prove strategy exposure but cannot transfer principal between lanes on their own.

## Parameters intentionally unset

This architecture does **not** choose:

- maximum amount a sleeve may lend;
- maximum borrower exposure;
- maximum portfolio amount leased;
- protected reserve size;
- idle-duration requirement;
- lease expiry;
- lender or borrower priority;
- profit attribution;
- loss attribution.

Those decisions need natural utilization evidence.

## Evidence required first

Once the genuine PAPER portfolio is operating, measure:

- realized equity by lane;
- available/reserved/deployed capital;
- qualified trades blocked only by capital;
- capital-vs-execution downsizing;
- how long capital is genuinely unused while the home lane has no qualified demand;
- simultaneous capital demand across lanes;
- counterfactual return/drawdown under candidate lease limits.

Only then should exact lease parameters be frozen.

## Stage-E isolation

No Stage-E source, candidate, workflow, diagnostic budget or workload is changed.

No runtime implementation, allocation authority, market run, or live-money authority is introduced.
