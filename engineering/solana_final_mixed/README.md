# Model B final mixed proof

Final disposition: **BLOCKED_BY_SPECIFIC_EVIDENCE_OR_PROVIDER_CONSTRAINT**. See [the owner report](REPORT.md) and [measured results](measurements.json). Provider access is stopped; this proof did not certify operational PAPER readiness or monthly production costs.

The proof uses the production source, shared Governor, canonical PriorityOwner, native candidate and position evidence paths, and the two-worker limit. It opens disposable evidence state only. Model A remains archived.

The owner observer samples the actual queue without submitting health work. A pre-stop census separates normal running drain from shutdown. Incomplete continuation history is not a complete position sample. Failed or deferred hydration timestamps are not qualification-ready vectors. The final report will retain all censored work and exact pending identities.

Run `python -m engineering.solana_capacity.final_mixed --seconds 180 --output <new-directory>`, then `python -m engineering.solana_capacity.audit_final_mixed <directory>`. Provider response/frame archives are streamed through lossless compression. Provider-byte accounting counts delivered bytes before local compression and deduplication.
