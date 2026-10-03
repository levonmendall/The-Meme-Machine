Existing SOL/USD authority: Pump Survivor's authenticated Pyth PriceUpdateV2 account
`7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE`, with owner, feed, full verification,
publish age and slot checks. Pump and Meteora can reuse that decoder and shared
Solana evidence. No historical fixed genesis SOL price is an operational USD rate.

Existing Robinhood conversion: Ramses `ramses_costs.quote_native_cycle` authenticates
bounded executable WNATIVE→quote routes, including USDG. This is a token conversion,
not a USD value. Pons's old frozen ETH/USD entry-gate translation is historical
strategy calibration, not a current portfolio valuation feed. Ramses's USDG quote
selection does not state USD parity. Documentation explicitly calls its ledger
values raw token amounts, not whole dollars.

Exact remaining anchor: authoritative USDG/USD valuation (or an already frozen
contractual USD parity). Once supplied through an approved existing evidence path,
the existing native→USDG routes can complete Pons valuation as well. The branch
contains no invented parity, manual exchange-rate override or new paid provider.
All other work continues offline. No genuine portfolio epoch is initialized here.
