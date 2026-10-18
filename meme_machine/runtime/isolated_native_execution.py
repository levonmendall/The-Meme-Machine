"""Explicit execution scope that can only remove financial authority.

No environment setting selects this scope. Native bootstrap owners enter it
explicitly; spawned preparers can install the deny-only sentinel without any
resource, epoch or positive sizing capability. Context does not automatically
cross new threads/processes: each initializer must install it deliberately.
"""
from contextlib import contextmanager
from contextvars import ContextVar


class IsolatedFinancialWriteDenied(ValueError):
    pass


_DENY_ONLY = object()
_execution = ContextVar('isolated_native_deny_financial_writes',default=None)


def financial_writes_denied():
    return _execution.get() is not None


def install_isolated_native_execution(native_resources=None):
    """Explicit worker initializer; it provides no positive capability."""
    if native_resources is not None:
        from meme_machine.runtime.isolated_native_resources import require_resources
        require_resources(native_resources)
    active = _execution.get()
    if (active is not None and active is not _DENY_ONLY and native_resources is not None
            and active is not native_resources):
        raise ValueError('isolated_native_execution_scope_mismatch')
    return _execution.set(_DENY_ONLY if native_resources is None else native_resources)


@contextmanager
def isolated_native_execution(native_resources=None):
    token = install_isolated_native_execution(native_resources)
    try:
        yield
    finally:
        _execution.reset(token)


def reject_financial_construction(native_resources=None):
    """Call before any path creation, SQLite open, genesis or recovery."""
    if native_resources is not None:
        from meme_machine.runtime.isolated_native_resources import require_resources
        require_resources(native_resources)
    if native_resources is not None or financial_writes_denied():
        raise IsolatedFinancialWriteDenied('isolated_native_financial_constructor_denied')
