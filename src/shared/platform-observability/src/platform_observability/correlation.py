"""Correlation and request context tracking across execution boundaries."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

# Context variables bound to asynchronous task scope
_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_correlation_id() -> str:
    """Obtain active correlation ID, generating a fallback UUID if unbound."""
    cid = _CORRELATION_ID.get()
    if cid is None:
        cid = str(uuid4())
        _CORRELATION_ID.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """Explicitly bind correlation ID to the current context."""
    _CORRELATION_ID.set(correlation_id)


def get_request_id() -> str:
    """Obtain active request ID, generating a fallback UUID if unbound."""
    rid = _REQUEST_ID.get()
    if rid is None:
        rid = str(uuid4())
        _REQUEST_ID.set(rid)
    return rid


def set_request_id(request_id: str) -> None:
    """Explicitly bind request ID to the current context."""
    _REQUEST_ID.set(request_id)


@contextmanager
def CorrelationContext(
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> Generator[str, None, None]:
    """Context manager for binding a correlation and request ID to an execution scope."""
    c_id = correlation_id or str(uuid4())
    r_id = request_id or str(uuid4())

    token_cid = _CORRELATION_ID.set(c_id)
    token_rid = _REQUEST_ID.set(r_id)
    try:
        yield c_id
    finally:
        _CORRELATION_ID.reset(token_cid)
        _REQUEST_ID.reset(token_rid)
