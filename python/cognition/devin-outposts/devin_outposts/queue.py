"""Typed sync client for the Devin Outposts opbeta queue API.

The API is early-access and endpoint shapes change, so this client deliberately
stays thin while the separate tolerance layer normalizes payloads.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote

import httpx


LOGGER = logging.getLogger(__name__)

JSONMap = dict[str, Any]


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """A Devin Outposts queue resource with parsed convenience fields."""

    session_id: str | None
    outpost_id: str | None = None
    kind: str | None = None
    platform: str | None = None
    remote_binary_sha: str | None = None
    phase: str | None = None
    acceptor_id: str | None = None
    claim_deadline: str | None = None
    session_status: str | None = None
    metadata: JSONMap = field(default_factory=dict)
    spec: JSONMap = field(default_factory=dict)
    status: JSONMap = field(default_factory=dict)
    raw: JSONMap = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> QueueEntry:
        """Parse the queue resource shape while retaining the original payload."""
        raw = _as_dict(payload)
        metadata = _as_dict(raw.get("metadata"))
        spec = _as_dict(raw.get("spec"))
        status = _as_dict(raw.get("status"))

        return cls(
            session_id=_str_or_none(
                _first_present(
                    _get(metadata, "session_id", "sessionId", "id"),
                    _get(raw, "session_id", "sessionId", "id"),
                )
            ),
            outpost_id=_str_or_none(
                _first_present(
                    _get(metadata, "outpost_id", "outpostId"),
                    _get(spec, "outpost_id", "outpostId"),
                    _get(raw, "outpost_id", "outpostId"),
                )
            ),
            kind=_str_or_none(_first_present(_get(spec, "kind"), _get(raw, "kind"))),
            platform=_str_or_none(
                _first_present(_get(spec, "platform"), _get(raw, "platform"))
            ),
            remote_binary_sha=_str_or_none(
                _first_present(
                    _get(spec, "remote_binary_sha", "remoteBinarySha"),
                    _get(raw, "remote_binary_sha", "remoteBinarySha"),
                )
            ),
            phase=_str_or_none(
                _first_present(_get(status, "phase"), _get(raw, "phase"))
            ),
            acceptor_id=_str_or_none(
                _first_present(
                    _get(status, "acceptor_id", "acceptorId"),
                    _get(raw, "acceptor_id", "acceptorId"),
                )
            ),
            claim_deadline=_str_or_none(
                _first_present(
                    _get(status, "claim_deadline", "claimDeadline"),
                    _get(raw, "claim_deadline", "claimDeadline"),
                )
            ),
            session_status=_str_or_none(
                _first_present(
                    _get(status, "session_status", "sessionStatus"),
                    _get(raw, "session_status", "sessionStatus"),
                )
            ),
            metadata=metadata,
            spec=spec,
            status=status,
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class Event:
    """One SSE queue event, including the replay cursor from the JSON frame."""

    cursor: str | None
    event: str | None = None
    session_id: str | None = None
    entry: QueueEntry | None = None
    raw: JSONMap = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        sse_event: str | None = None,
        sse_id: str | None = None,
    ) -> Event:
        """Parse a watch JSON frame into a typed event."""
        raw = _as_dict(payload)
        entry_payload = _find_entry_payload(raw)
        entry = QueueEntry.from_payload(entry_payload) if entry_payload else None
        cursor = _str_or_none(
            _first_present(
                _get(raw, "cursor"),
                _get(raw, "next_cursor", "nextCursor"),
                sse_id,
            )
        )
        event = _str_or_none(
            _first_present(
                _get(raw, "event", "type", "action", "op"),
                sse_event,
            )
        )
        session_id = _str_or_none(
            _first_present(
                _get(raw, "session_id", "sessionId"),
                entry.session_id if entry else None,
            )
        )
        return cls(
            cursor=cursor,
            event=event,
            session_id=session_id,
            entry=entry,
            raw=raw,
        )


@dataclass(frozen=True, slots=True)
class Page:
    """A page of queue entries returned by the list endpoint."""

    items: list[QueueEntry]
    cursor: str | None = None
    has_next_page: bool = False
    raw: JSONMap = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> Page:
        """Parse list responses shaped as a page object or a bare item array."""
        if isinstance(payload, list):
            return cls(
                items=[QueueEntry.from_payload(item) for item in payload],
                raw={"items": payload},
            )

        raw = _as_dict(payload)
        item_payloads = _first_present(
            _get(raw, "items"),
            _get(raw, "devins"),
            _get(raw, "data"),
            _get(raw, "results"),
            [],
        )
        if not isinstance(item_payloads, list):
            item_payloads = []

        return cls(
            items=[QueueEntry.from_payload(item) for item in item_payloads],
            cursor=_str_or_none(
                _first_present(
                    _get(raw, "cursor"),
                    _get(raw, "end_cursor", "endCursor"),
                    _get(raw, "next_cursor", "nextCursor"),
                )
            ),
            has_next_page=bool(
                _first_present(_get(raw, "has_next_page", "hasNextPage"), False)
            ),
            raw=raw,
        )


class DevinQueueError(Exception):
    """Base error raised for Devin queue request or response failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class Conflict(DevinQueueError):
    """Raised when an atomic claim/release request loses an HTTP 409 race."""


class DevinQueue:
    """Thin synchronous client for the Devin Outposts opbeta queue API."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> DevinQueue:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def list(
        self,
        outpost: str | None = None,
        phase: str | None = None,
        acceptor_id: str | None = None,
        cursor: str | None = None,
        first: int = 200,
    ) -> Page:
        """List queued Devin sessions, optionally filtered and paginated."""
        payload = self._request_json(
            "GET",
            "/outposts/devins",
            params=_drop_none(
                {
                    "outpost": outpost,
                    "phase": phase,
                    "acceptor_id": acceptor_id,
                    "cursor": cursor,
                    "first": first,
                }
            ),
        )
        return Page.from_payload(payload)

    def get(self, session_id: str) -> QueueEntry:
        """Fetch one queue entry by Devin queue session ID."""
        payload = self._request_json("GET", f"/outposts/devins/{_quote(session_id)}")
        return QueueEntry.from_payload(_unwrap_entry_payload(payload))

    def claim(self, session_id: str, acceptor_id: str) -> QueueEntry | dict[str, Any]:
        """Atomically claim a queue entry for this acceptor."""
        return self._entry_or_raw(
            self._request_json(
                "POST",
                f"/outposts/devins/{_quote(session_id)}/claim",
                json={"acceptor_id": acceptor_id},
            )
        )

    def release(self, session_id: str, acceptor_id: str) -> QueueEntry | dict[str, Any]:
        """Release a queue entry previously claimed by this acceptor."""
        return self._entry_or_raw(
            self._request_json(
                "POST",
                f"/outposts/devins/{_quote(session_id)}/release",
                json={"acceptor_id": acceptor_id},
            )
        )

    def watch(
        self, outpost: str | None = None, cursor: str | None = None
    ) -> Iterator[Event]:
        params = _drop_none({"outpost": outpost, "cursor": cursor, "watch": "true"})
        try:
            with self._client.stream(
                "GET",
                self._url("/outposts/devins"),
                params=params,
                headers={"Accept": "text/event-stream"},
            ) as response:
                self._raise_for_status(response)
                yield from self._parse_sse(response.iter_lines())
        except DevinQueueError:
            raise
        except httpx.RequestError as exc:
            raise DevinQueueError(f"Devin queue request failed: {exc}") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                self._url(path),
                params=params,
                json=json,
            )
        except httpx.RequestError as exc:
            raise DevinQueueError(f"Devin queue request failed: {exc}") from exc

        self._raise_for_status(response)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise DevinQueueError(
                "Devin queue response was not valid JSON",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        body = _response_text(response)
        message = _error_message(response.status_code, body)
        error_type = Conflict if response.status_code == 409 else DevinQueueError
        raise error_type(
            message,
            status_code=response.status_code,
            response_body=body,
        )

    def _entry_or_raw(self, payload: Any) -> QueueEntry | dict[str, Any]:
        if not isinstance(payload, Mapping):
            return {"raw": payload}
        try:
            return QueueEntry.from_payload(_unwrap_entry_payload(payload))
        except DevinQueueError:
            return dict(payload)

    def _parse_sse(self, lines: Iterable[str]) -> Iterator[Event]:
        event_name: str | None = None
        data_lines: list[str] = []
        event_id: str | None = None

        for raw_line in lines:
            line = raw_line.rstrip("\r")
            if not line:
                event = _watch_event_from_data(data_lines, event_name, event_id)
                if event is not None:
                    yield event
                event_name = None
                data_lines = []
                continue

            if line.startswith(":"):
                continue

            field_name, separator, value = line.partition(":")
            if not separator:
                value = ""
            elif value.startswith(" "):
                value = value[1:]

            if field_name == "data":
                data_lines.append(value)
            elif field_name == "event":
                event_name = value or None
            elif field_name == "id":
                event_id = value

        event = _watch_event_from_data(data_lines, event_name, event_id)
        if event is not None:
            yield event

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"


def _normalize_base_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    if base.endswith("/opbeta"):
        return base
    return f"{base}/opbeta"


def _quote(value: str) -> str:
    return quote(value, safe="")


def _drop_none(values: Mapping[str, Any]) -> JSONMap:
    return {key: value for key, value in values.items() if value is not None}


def _as_dict(value: Any) -> JSONMap:
    return dict(value) if isinstance(value, Mapping) else {}


def _get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _has_entry_shape(value: Any) -> bool:
    return isinstance(value, Mapping) and any(
        key in value
        for key in (
            "metadata",
            "spec",
            "status",
            "session_id",
            "sessionId",
            "outpost_id",
            "outpostId",
        )
    )


def _find_entry_payload(payload: Mapping[str, Any]) -> JSONMap | None:
    for key in ("entry", "devin", "item", "resource", "data"):
        value = payload.get(key)
        if _has_entry_shape(value):
            return dict(value)

    if _has_entry_shape(payload):
        return dict(payload)
    return None


def _unwrap_entry_payload(payload: Mapping[str, Any]) -> JSONMap:
    entry = _find_entry_payload(payload)
    if entry is None:
        raise DevinQueueError("Devin queue response did not contain a queue entry")
    return entry


def _watch_event_from_data(
    data_lines: list[str], sse_event: str | None, sse_id: str | None
) -> Event | None:
    if not data_lines:
        return None

    data = "\n".join(data_lines)
    if not data:
        return Event(cursor=sse_id, event=sse_event, raw={"data": ""})

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        payload = {"data": data}

    if isinstance(payload, Mapping):
        return Event.from_payload(payload, sse_event=sse_event, sse_id=sse_id)
    return Event(cursor=sse_id, event=sse_event, raw={"data": payload})


def _response_text(response: httpx.Response) -> str:
    try:
        return response.text
    except httpx.ResponseNotRead:
        return response.read().decode(errors="replace")


def _error_message(status_code: int, body: str) -> str:
    detail = body.strip()
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None

    if isinstance(parsed, Mapping):
        detail = str(
            _first_present(
                parsed.get("detail"),
                parsed.get("message"),
                parsed.get("error"),
                detail,
            )
        )

    return f"Devin queue API returned HTTP {status_code}: {detail}"
