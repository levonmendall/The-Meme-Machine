# v9 launch guard reauthorization

The first v9 dispatch (run 36038607202) consumed authorization v1 but was blocked
before provider or market work because certification.guard did not recognize the
new v9 non-market certification wrapper as reviewed offline work.

This repair keeps unknown workflows fail-closed, while explicitly classifying the
reviewed v9 handoff non-market wrapper's offline-prerequisites job as non-market.

No strategy, provider, market scope, evidence, accounting, or lifecycle economics
change. Authorization v2 is required because v1 was durably consumed.

Focused validation follows.
