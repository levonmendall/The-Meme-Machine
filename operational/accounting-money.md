# Canonical PAPER money

`meme_machine.exact_money` owns the fixed-point USD contract shared by valuation,
lane admission, accounting replay/mutations/checkpoints/export, snapshot transport
and the dashboard Reader. Monetary values use exact decimal text or Decimal,
at most 40 integer digits and 29 fractional places. Binary float, scientific
notation on the wire, nonfinite values, excessive magnitude or scale fail
explicitly. Computed authoritative components must remain inside that envelope.

The existing paths derive these scales without rounding: SOL raw lamports (9)
times conservative oracle micros (6) needs 15 places; USDG raw units (6) times
the authenticated oracle answer (8) needs 14. Pons uses an executable integer
USDG quote for the existing 10^15 native-unit ETH probe. Its composed USD amount
is `ETH_raw * USDG_quote_raw * oracle_answer / 10^(15+6+8)`, needing 29 places.
The 18-place ETH denomination cancels between unit price and raw amount. No
conversion normalization, lossy quantization or replacement market value occurs.

Canonical arithmetic has a fully specified thread-local context with 154
significant digits and traps for inexact/rounded results. It never changes the
caller context. Addition/subtraction and accumulation preserve accepted money
exactly; reconciliation validates resulting bounds before journal commit.
Canonical serialization preserves fixed-point scale, so replay is deterministic.
Read-only dashboard ratios and averages may be recurring decimals: they use
the same explicit precision with deterministic half-even reporting, without
feeding those display ratios back into accounting or capital authority.

Native partial basis allocation can be a recurring rational after entries/adds
at different USD rates. At that boundary only, integer arithmetic takes the
ceiling of `remaining_USD_basis * native_basis_released / native_basis_before`
in 10^-29 USD units. Exact terminating fractions remain exact. The sub-unit
conservative excess reduces realized P&L/sleeve capital, never increases cash,
and cannot exceed remaining basis; an unrepresentable nonterminal fraction
fails explicitly. This happens once before durable pending delivery. Canonical
replay uses the stored fixed-point fact, with no repeated normalization.

A partial realization/harvest or rebalance (including a mixed release/add with
unchanged net basis) invalidates the prior open-position mark to UNAVAILABLE.
Only a subsequent genuine canonical USD mark can restore CURRENT. Settlement
removes it. Old journal events replay under this rule; an old checkpoint's
ordered canonical lifecycle suffix identifies an exposure mutation after its
last monitoring event and invalidates that mark in the recovered projection.
Neither historical journal bytes nor economic identities are rewritten.
