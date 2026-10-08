"""Transaction identity checks; no strategy, market, or freshness authority."""

# Base58 encoding of the SDK default 64 zero bytes. This is not a signed tx id.
DEFAULT_SIGNATURE = "1" * 64


def is_default_signature(value):
    return value == DEFAULT_SIGNATURE
