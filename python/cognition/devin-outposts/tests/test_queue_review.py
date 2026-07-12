from __future__ import annotations

import unittest
from collections.abc import Iterator
from typing import Any

import httpx

from devin_outposts.queue import DevinQueue, DevinQueueError, Event, QueueEntry
from devin_outposts.queue_shapes import (
    claim_status_value,
    entry_session_id,
    event_session_id,
    unpack_page,
)


class QueueShapeReviewTests(unittest.TestCase):
    def test_entry_session_id_matches_queue_entry_aliases_and_precedence(self) -> None:
        payloads = (
            {"sessionId": "top-camel"},
            {"id": "top-id"},
            {"metadata": {"sessionId": "metadata-camel"}},
            {"metadata": {"id": "metadata-id"}},
            {
                "sessionId": "top-camel",
                "metadata": {"sessionId": "metadata-camel"},
            },
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                expected = QueueEntry.from_payload(payload).session_id
                self.assertEqual(entry_session_id(payload), expected)

    def test_delete_event_accepts_top_level_camel_case_session_id(self) -> None:
        event = {"type": "DELETED", "sessionId": "deleted-session"}

        self.assertEqual(event_session_id(event), "deleted-session")

    def test_unpack_page_accepts_cursor_aliases_and_derives_has_next(self) -> None:
        items, cursor, has_next = unpack_page({"items": [], "nextCursor": "next-page"})
        self.assertEqual(items, [])
        self.assertEqual(cursor, "next-page")
        self.assertTrue(has_next)

        _, cursor, has_next = unpack_page(
            {"items": [], "endCursor": "last-page", "hasNextPage": False}
        )
        self.assertEqual(cursor, "last-page")
        self.assertFalse(has_next)

    def test_claim_status_falls_back_to_top_level_mapping(self) -> None:
        claim = {
            "status": {"phase": "claimed", "gatewayUrl": "nested-gateway"},
            "gatewayUrl": "top-gateway",
            "connectToken": "top-token",
        }

        self.assertEqual(
            claim_status_value(claim, "gateway_url", "gatewayUrl"),
            "nested-gateway",
        )
        self.assertEqual(
            claim_status_value(claim, "connect_token", "connectToken"),
            "top-token",
        )

    def test_claim_status_falls_back_to_queue_entry_raw_payload(self) -> None:
        claim = QueueEntry.from_payload(
            {
                "sessionId": "claimed-session",
                "status": {"phase": "claimed"},
                "gatewayUrl": "top-gateway",
                "connectToken": "top-token",
            }
        )

        self.assertEqual(
            claim_status_value(claim, "gateway_url", "gatewayUrl"),
            "top-gateway",
        )
        self.assertEqual(
            claim_status_value(claim, "connect_token", "connectToken"),
            "top-token",
        )

    def test_event_entry_prefers_supported_wrapper_over_envelope_status(self) -> None:
        event = Event.from_payload(
            {
                "status": "ok",
                "data": {
                    "sessionId": "wrapped-session",
                    "status": {"phase": "queued"},
                },
            }
        )

        self.assertIsNotNone(event.entry)
        assert event.entry is not None
        self.assertEqual(event.entry.session_id, "wrapped-session")
        self.assertEqual(event.entry.phase, "queued")


class FakeStreamContext:
    def __init__(self, response: Any) -> None:
        self.response = response

    def __enter__(self) -> Any:
        return self.response

    def __exit__(self, *_exc: object) -> None:
        return None


class ReadFailureResponse:
    status_code = 200

    def iter_lines(self) -> Iterator[str]:
        yield 'data: {"sessionId":"first-session"}'
        yield ""
        raise httpx.ReadError(
            "stream read failed",
            request=httpx.Request("GET", "https://example.test/watch"),
        )


class FakeStreamClient:
    def __init__(
        self, response: Any = None, error: httpx.RequestError | None = None
    ) -> None:
        self.response = response
        self.error = error

    def stream(self, *_args: Any, **_kwargs: Any) -> FakeStreamContext:
        if self.error is not None:
            raise self.error
        return FakeStreamContext(self.response)


class QueueWatchReviewTests(unittest.TestCase):
    def make_queue(self, client: FakeStreamClient) -> DevinQueue:
        queue = DevinQueue("https://example.test", "token")
        queue._client.close()
        queue._client = client  # type: ignore[assignment]
        return queue

    def test_watch_wraps_connection_request_errors(self) -> None:
        request = httpx.Request("GET", "https://example.test/watch")
        queue = self.make_queue(
            FakeStreamClient(
                error=httpx.ConnectError("connect failed", request=request)
            )
        )

        with self.assertRaises(DevinQueueError) as raised:
            list(queue.watch())

        self.assertIsInstance(raised.exception.__cause__, httpx.ConnectError)
        self.assertIn("Devin queue request failed", str(raised.exception))

    def test_watch_wraps_stream_read_request_errors(self) -> None:
        queue = self.make_queue(FakeStreamClient(ReadFailureResponse()))

        with self.assertRaises(DevinQueueError) as raised:
            list(queue.watch())

        self.assertIsInstance(raised.exception.__cause__, httpx.ReadError)
        self.assertIn("Devin queue request failed", str(raised.exception))

    def test_watch_preserves_status_errors(self) -> None:
        response = httpx.Response(503, text="temporarily unavailable")
        queue = self.make_queue(FakeStreamClient(response))

        with self.assertRaises(DevinQueueError) as raised:
            list(queue.watch())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIn("returned HTTP 503", str(raised.exception))

    def test_sse_field_rules_and_last_event_id_persistence(self) -> None:
        queue = DevinQueue("https://example.test", "token")
        self.addCleanup(queue.close)

        events = list(
            queue._parse_sse(
                (
                    "id: first-id",
                    'data: {"type":"ADDED"}',
                    "",
                    'data: {"type":"UPDATED"}',
                    "",
                    "id",
                    "data",
                    "",
                    'data: {"type":"UPDATED"}',
                    "",
                )
            )
        )

        self.assertEqual(
            [event.cursor for event in events], ["first-id", "first-id", "", ""]
        )
        self.assertEqual(events[2].raw, {"data": ""})
