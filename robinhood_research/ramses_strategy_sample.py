"""Compatibility entrypoint for the connected all-pool Ramses lifecycle.

The legacy native-only selector is intentionally not used. Existing strategy
workflow triggers now enter the all-pool Fee Pulse selector and, on the first
genuine qualifier, continue through the independent LP lifecycle.
"""
from .ramses_all_pool_lifecycle import main


if __name__ == "__main__":
    main()
