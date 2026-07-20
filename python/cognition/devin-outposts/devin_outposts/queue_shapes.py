"""Normalize beta queue payloads for the orchestrator.

Fields drift between top-level and nested ``status``, ``metadata``, or ``spec``
locations, represented as mappings or objects. These accessors absorb that
variation so orchestration code reads one stable shape.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from .queue import QueueEntry

LOGGER = logging.getLogger(__name__)


def entry_session_id(entry: Any) -> str | None:
    metadata = _field(entry, "metadata")
    return (
        _string_field(metadata, "session_id")
        or _string_field(metadata, "sessionId")
        or _string_field(metadata, "id")
        or _string_field(entry, "session_id")
        or _string_field(entry, "sessionId")
        or _string_field(entry, "id")
    )


def require_session_id(entry: Any) -> str:
    session_id = entry_session_id(entry)
    if not session_id:
        raise RuntimeError("queue entry is missing session_id")
    return session_id


def entry_outpost_id(entry: Any) -> str | None:
    return (
        _string_field(entry, "outpost_id")
        or _string_field(entry, "outpostId")
        or _string_field(_field(entry, "metadata"), "outpost_id")
        or _string_field(_field(entry, "metadata"), "outpostId")
    )


def entry_phase(entry: Any) -> str | None:
    value = _string_field(entry, "phase") or _string_field(
        _field(entry, "status"), "phase"
    )
    return value.lower() if value else None


def entry_platform(entry: Any) -> str:
    value = _string_field(entry, "platform") or _string_field(
        _field(entry, "spec"), "platform"
    )
    return value.lower() if value else "linux"


def entry_acceptor_id(entry: Any) -> str | None:
    return _string_field(entry, "acceptor_id") or _string_field(
        _field(entry, "status"), "acceptor_id"
    )


def entry_session_status(entry: Any) -> str | None:
    value = _string_field(entry, "session_status") or _string_field(
        _field(entry, "status"), "session_status"
    )
    return value.lower() if value else None


def event_entry(event: Any) -> Any | None:
    return (
        _field(event, "entry")
        or _field(event, "item")
        or _field(event, "devin")
        or _field(event, "resource")
        or _field(event, "data")
    )


def event_cursor(event: Any) -> str | None:
    return (
        _string_field(event, "cursor")
        or _string_field(event, "next_cursor")
        or _string_field(event, "nextCursor")
        or _string_field(event, "id")
    )


def event_session_id(event: Any) -> str | None:
    return (
        entry_session_id(event_entry(event))
        or _string_field(event, "session_id")
        or _string_field(event, "sessionId")
    )


def event_is_deleted(event: Any) -> bool:
    raw = _field(event, "raw")
    value = (
        _string_field(event, "type")
        or _string_field(event, "event")
        or _string_field(event, "op")
        or _string_field(raw, "type")
        or _string_field(raw, "event")
        or _string_field(raw, "op")
        or ""
    )
    return value.upper() in {"DELETED", "DELETE", "REMOVED"}


def unpack_page(page: Any) -> tuple[list[QueueEntry], str | None, bool]:
    if isinstance(page, tuple):
        if len(page) == 3:
            items, cursor, has_next = page
            return list(items), _coerce_optional_string(cursor), bool(has_next)
        if len(page) == 2:
            items, cursor = page
            return list(items), _coerce_optional_string(cursor), bool(cursor)
    if isinstance(page, list):
        return page, None, False
    items = (
        _field(page, "items") or _field(page, "entries") or _field(page, "data") or []
    )
    cursor = (
        _string_field(page, "cursor")
        or _string_field(page, "next_cursor")
        or _string_field(page, "nextCursor")
        or _string_field(page, "end_cursor")
        or _string_field(page, "endCursor")
    )
    has_next_value = _first_field(page, "has_next_page", "hasNextPage", "has_next")
    has_next = (
        bool(has_next_value) if has_next_value is not None else cursor is not None
    )
    return list(items), cursor, has_next


def claim_status_value(
    claim: QueueEntry | Mapping[str, Any], *names: str
) -> str | None:
    sources: tuple[Mapping[str, Any], ...]
    if isinstance(claim, QueueEntry):
        sources = (claim.status, claim.raw)
    else:
        candidate = claim.get("status")
        status = candidate if isinstance(candidate, Mapping) else {}
        sources = (status, claim)
    for source in sources:
        for name in names:
            value = source.get(name)
            if value is not None and str(value).strip():
                return str(value)
    return None


def _field(obj: Any, name: str) -> Any | None:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _first_field(obj: Any, *names: str) -> Any | None:
    for name in names:
        value = _field(obj, name)
        if value is not None:
            return value
    return None


def _string_field(obj: Any, name: str) -> str | None:
    value = _field(obj, name)
    return _coerce_optional_string(value)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
