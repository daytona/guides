from __future__ import annotations

import io
import os
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import httpx

from devin_outposts.connect import (
    CALLBACK_URL,
    CONNECT_URL,
    TOKEN_URL,
    CallbackListener,
    ConnectError,
    ConnectionCredentials,
    build_connect_url,
    exchange_code,
    generate_pkce,
    main,
    update_env_file,
)

RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class PkceTests(unittest.TestCase):
    def test_generate_pkce_matches_rfc7636_s256_example(self) -> None:
        with patch("devin_outposts.connect.secrets.token_urlsafe", return_value=RFC7636_VERIFIER):
            verifier, challenge = generate_pkce()

        self.assertEqual(verifier, RFC7636_VERIFIER)
        self.assertEqual(challenge, RFC7636_CHALLENGE)

    def test_generate_pkce_uses_unreserved_unpadded_values(self) -> None:
        verifier, challenge = generate_pkce()

        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertRegex(verifier, r"^[A-Za-z0-9._~-]+$")
        self.assertRegex(challenge, r"^[A-Za-z0-9_-]+$")
        self.assertNotIn("=", challenge)

    def test_connect_url_contains_only_documented_browser_fields(self) -> None:
        url = build_connect_url("challenge-value", "daytona-windows", "windows")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", CONNECT_URL)
        self.assertEqual(
            query,
            {
                "callback_url": [CALLBACK_URL],
                "outpost_name": ["daytona-windows"],
                "platform": ["windows"],
                "code_challenge": ["challenge-value"],
            },
        )
        self.assertNotIn(RFC7636_VERIFIER, url)


class CallbackListenerTests(unittest.TestCase):
    def test_callback_ignores_unrelated_and_malformed_requests(self) -> None:
        responses: list[httpx.Response] = []
        errors: list[BaseException] = []

        with CallbackListener(host="127.0.0.1", port=0) as listener:
            base_url = f"http://127.0.0.1:{listener.port}"

            def send_requests() -> None:
                try:
                    responses.append(httpx.get(f"{base_url}/favicon.ico", timeout=5))
                    responses.append(httpx.get(f"{base_url}/callback", timeout=5))
                    responses.append(
                        httpx.get(f"{base_url}/callback?code=one&code=two", timeout=5)
                    )
                    responses.append(
                        httpx.get(f"{base_url}/callback?code=code%2Bvalue", timeout=5)
                    )
                except BaseException as exc:  # surfaced on the test thread below
                    errors.append(exc)

            request_thread = threading.Thread(target=send_requests)
            request_thread.start()
            code = listener.wait(timeout=5)
            request_thread.join(timeout=5)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual([response.status_code for response in responses], [404, 400, 400, 200])
        self.assertEqual(code, "code+value")
        self.assertEqual(responses[-1].headers["cache-control"], "no-store")
        self.assertIn("Authorization received", responses[-1].text)

    def test_callback_error_is_sanitized_and_terminates_wait(self) -> None:
        responses: list[httpx.Response] = []
        errors: list[BaseException] = []

        with CallbackListener(host="127.0.0.1", port=0) as listener:
            callback_url = f"http://127.0.0.1:{listener.port}/callback"

            def send_error() -> None:
                try:
                    responses.append(
                        httpx.get(
                            callback_url,
                            params={
                                "error": "access_denied",
                                "error_description": "Denied\nby admin",
                            },
                            timeout=5,
                        )
                    )
                except BaseException as exc:  # surfaced on the test thread below
                    errors.append(exc)

            request_thread = threading.Thread(target=send_error)
            request_thread.start()
            with self.assertRaisesRegex(ConnectError, "Denied by admin") as caught:
                listener.wait(timeout=5)
            request_thread.join(timeout=5)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(responses[0].status_code, 400)
        self.assertEqual(responses[0].headers["cache-control"], "no-store")
        self.assertIn("Devin authorization failed", responses[0].text)
        self.assertNotIn("\n", str(caught.exception))
        self.assertNotIn("error_description", str(caught.exception))


class TokenExchangeTests(unittest.TestCase):
    def test_exchange_is_unauthenticated_form_post(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual(str(request.url), TOKEN_URL)
            self.assertEqual(request.method, "POST")
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(
                parse_qs(request.content.decode("ascii")),
                {
                    "grant_type": ["authorization_code"],
                    "code": ["one-time-code"],
                    "code_verifier": ["local-verifier"],
                },
            )
            return httpx.Response(
                200,
                json={
                    "outpost_id": "outpost_env_outpost",
                    "access_token": "cog_machine_secret",
                    "api_base_url": "https://api.devin.ai/opbeta/",
                    "outpost_name": "daytona-linux",
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            credentials = exchange_code("one-time-code", "local-verifier", client)

        self.assertEqual(
            credentials,
            ConnectionCredentials(
                outpost_id="outpost_env_outpost",
                access_token="cog_machine_secret",
                api_base_url="https://api.devin.ai",
                outpost_name="daytona-linux",
            ),
        )

    def test_invalid_grant_exposes_only_sanitized_description(self) -> None:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": (
                        "Invalid\none-time-secret verifier-secret cog_response_secret"
                    ),
                    "access_token": "cog_response_secret",
                },
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(ConnectError) as caught:
                exchange_code("one-time-secret", "verifier-secret", client)

        message = str(caught.exception)
        self.assertIn("Invalid", message)
        self.assertNotIn("one-time-secret", message)
        self.assertNotIn("verifier-secret", message)
        self.assertNotIn("cog_response_secret", message)
        self.assertNotIn("\n", message)

    def test_exchange_rejects_malformed_or_incomplete_success(self) -> None:
        responses = (
            httpx.Response(200, text="not-json"),
            httpx.Response(
                200,
                json={
                    "outpost_id": "outpost_env_outpost",
                    "access_token": "cog_secret",
                },
            ),
        )
        for response in responses:
            with self.subTest(response=response):
                with httpx.Client(
                    transport=httpx.MockTransport(lambda _request, value=response: value)
                ) as client:
                    with self.assertRaises(ConnectError) as caught:
                        exchange_code("one-time-secret", "verifier-secret", client)
                self.assertNotIn("one-time-secret", str(caught.exception))
                self.assertNotIn("verifier-secret", str(caught.exception))
                self.assertNotIn("cog_secret", str(caught.exception))


class EnvFileTests(unittest.TestCase):
    def test_update_preserves_unrelated_content_and_collapses_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# local settings\n"
                "DEVIN_OUTPOSTS_TOKEN=old-token\n"
                "DAYTONA_API_KEY=daytona-key\n"
                "OUTPOST_ID=old-outpost\n"
                "OUTPOST_ID=stale-outpost\n"
                "DEVIN_API_URL=https://old.example/opbeta/\n"
                "# keep this comment\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o644)

            update_env_file(
                path,
                ConnectionCredentials(
                    outpost_id="outpost_env_new",
                    access_token="cog_new_secret",
                    api_base_url="https://api.devin.ai/opbeta/",
                ),
                force=True,
            )

            text = path.read_text(encoding="utf-8")
            self.assertIn("# local settings", text)
            self.assertIn("DAYTONA_API_KEY=daytona-key", text)
            self.assertIn("# keep this comment", text)
            self.assertEqual(text.count("DEVIN_OUTPOSTS_TOKEN="), 1)
            self.assertEqual(text.count("DEVIN_API_URL="), 1)
            self.assertEqual(text.count("OUTPOST_ID="), 1)
            self.assertIn("DEVIN_OUTPOSTS_TOKEN=cog_new_secret", text)
            self.assertIn("DEVIN_API_URL=https://api.devin.ai", text)
            self.assertIn("OUTPOST_ID=outpost_env_new", text)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_new_file_is_private_and_placeholder_file_needs_no_force(self) -> None:
        credentials = ConnectionCredentials(
            outpost_id="outpost_env_new",
            access_token="cog_new_secret",
            api_base_url="https://api.devin.ai",
        )
        with tempfile.TemporaryDirectory() as directory:
            new_path = Path(directory) / "new.env"
            update_env_file(new_path, credentials)
            self.assertEqual(
                new_path.read_text(encoding="utf-8"),
                "DEVIN_OUTPOSTS_TOKEN=cog_new_secret\n"
                "DEVIN_API_URL=https://api.devin.ai\n"
                "OUTPOST_ID=outpost_env_new\n",
            )
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(new_path.stat().st_mode), 0o600)

            placeholder_path = Path(directory) / ".env"
            placeholder_path.write_text(
                "DEVIN_OUTPOSTS_TOKEN=replace-with-devin-outposts-token\n"
                "OUTPOST_ID=outpost_env_replace_with_outpost_id\n",
                encoding="utf-8",
            )
            update_env_file(placeholder_path, credentials)
            self.assertIn("OUTPOST_ID=outpost_env_new", placeholder_path.read_text())


class MainFlowTests(unittest.TestCase):
    def test_configured_env_is_rejected_before_browser_or_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DEVIN_OUTPOSTS_TOKEN=cog_existing\nOUTPOST_ID=outpost_env_existing\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("devin_outposts.connect.webbrowser.open") as browser_open,
                patch("devin_outposts.connect.exchange_code") as exchange,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = main(["--env-file", str(path)])

        self.assertEqual(result, 2)
        browser_open.assert_not_called()
        exchange.assert_not_called()
        self.assertIn("--force", stderr.getvalue())
        self.assertIn("--env-file", stderr.getvalue())

    def test_success_binds_listener_before_browser_and_hides_secrets(self) -> None:
        events: list[str] = []
        credentials = ConnectionCredentials(
            outpost_id="outpost_env_new",
            access_token="cog_machine_secret",
            api_base_url="https://api.devin.ai",
            outpost_name="daytona-linux",
        )
        listener_type = self._listener_type(events, code="callback-code")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DEVIN_OUTPOSTS_TOKEN=replace-with-devin-outposts-token\n"
                "OUTPOST_ID=outpost_env_replace_with_outpost_id\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            def open_browser(_url: str) -> bool:
                events.append("browser-open")
                return False

            with (
                patch("devin_outposts.connect.CallbackListener", listener_type),
                patch(
                    "devin_outposts.connect.generate_pkce",
                    return_value=("verifier-secret", "challenge-safe"),
                ),
                patch("devin_outposts.connect.webbrowser.open", side_effect=open_browser),
                patch("devin_outposts.connect.exchange_code", return_value=credentials),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = main(["--env-file", str(path)])

            text = path.read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertLess(events.index("listener-created"), events.index("browser-open"))
        self.assertLess(events.index("browser-open"), events.index("listener-wait"))
        self.assertIn("A browser could not be opened automatically", stdout.getvalue())
        self.assertIn("DEVIN_OUTPOSTS_TOKEN=cog_machine_secret", text)
        combined_output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("cog_machine_secret", combined_output)
        self.assertNotIn("verifier-secret", combined_output)

    def test_force_replaces_existing_outpost_credentials(self) -> None:
        events: list[str] = []
        credentials = ConnectionCredentials(
            outpost_id="outpost_env_replacement",
            access_token="cog_replacement",
            api_base_url="https://api.devin.ai",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DEVIN_OUTPOSTS_TOKEN=cog_existing\nOUTPOST_ID=outpost_env_existing\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "devin_outposts.connect.CallbackListener",
                    self._listener_type(events, code="callback-code"),
                ),
                patch("devin_outposts.connect.webbrowser.open", return_value=True),
                patch("devin_outposts.connect.exchange_code", return_value=credentials),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                result = main(["--env-file", str(path), "--force"])
            text = path.read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertIn("DEVIN_OUTPOSTS_TOKEN=cog_replacement", text)
        self.assertIn("OUTPOST_ID=outpost_env_replacement", text)

    def test_timeout_and_interrupt_have_controlled_exit_codes(self) -> None:
        cases: tuple[tuple[BaseException, int], ...] = (
            (ConnectError("Timed out waiting for Devin authorization"), 2),
            (KeyboardInterrupt(), 130),
        )
        for error, expected in cases:
            with self.subTest(error=error):
                events: list[str] = []
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / ".env"
                    with (
                        patch(
                            "devin_outposts.connect.CallbackListener",
                            self._listener_type(events, error=error),
                        ),
                        patch("devin_outposts.connect.webbrowser.open", return_value=True),
                        patch("devin_outposts.connect.exchange_code") as exchange,
                        redirect_stdout(io.StringIO()),
                        redirect_stderr(io.StringIO()),
                    ):
                        result = main(["--env-file", str(path)])
                self.assertEqual(result, expected)
                exchange.assert_not_called()

    @staticmethod
    def _listener_type(
        events: list[str],
        *,
        code: str | None = None,
        error: BaseException | None = None,
    ) -> type:
        class FakeListener:
            def __init__(self) -> None:
                events.append("listener-created")

            def __enter__(self) -> "FakeListener":
                events.append("listener-enter")
                return self

            def __exit__(self, *_exc: object) -> None:
                events.append("listener-exit")

            def wait(self) -> str:
                events.append("listener-wait")
                if error is not None:
                    raise error
                assert code is not None
                return code

        return FakeListener


if __name__ == "__main__":
    unittest.main()
