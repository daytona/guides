"""Connect a Devin outpost and store its machine credentials locally."""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import os
import re
import secrets
import sys
import tempfile
import time
import webbrowser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast, override
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import dotenv_values

from .config import normalize_devin_api_url

CONNECT_URL = "https://app.devin.ai/outposts/connect"
TOKEN_URL = "https://api.devin.ai/outposts/connection-token"
CALLBACK_URL = "http://localhost:8765/callback"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8765
CALLBACK_TIMEOUT_SECONDS = 600.0
DEFAULT_ENV_FILE = Path(".env")

_MANAGED_ENV_KEYS = ("DEVIN_OUTPOSTS_TOKEN", "DEVIN_API_URL", "OUTPOST_ID")
_PLACEHOLDERS = {
    "DEVIN_OUTPOSTS_TOKEN": "replace-with-devin-outposts-token",
    "OUTPOST_ID": "outpost_env_replace_with_outpost_id",
}
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?(DEVIN_OUTPOSTS_TOKEN|DEVIN_API_URL|OUTPOST_ID)\s*="
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_UNQUOTED_ENV_VALUE = re.compile(r"^[A-Za-z0-9_./:+-]+$")


@dataclass(frozen=True, slots=True)
class ConnectionCredentials:
    outpost_id: str
    access_token: str
    api_base_url: str
    outpost_name: str | None = None


class ConnectError(RuntimeError):
    """Raised when Devin authorization or local credential storage fails."""


class CallbackListener:
    """One-shot loopback HTTP listener for Devin's authorization redirect."""

    def __init__(self, host: str = CALLBACK_HOST, port: int = CALLBACK_PORT) -> None:
        if host not in {"localhost", "127.0.0.1"}:
            raise ConnectError("The callback listener must bind to a loopback host")

        listener = self

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            @override
            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                listener._handle_request(self)

            @override
            def log_message(self, format: str, *args: object) -> None:
                del format, args

        try:
            self._server: http.server.HTTPServer = http.server.HTTPServer(
                (host, port), CallbackHandler
            )
        except OSError as exc:
            raise ConnectError(
                "Cannot listen on http://localhost:8765/callback; "
                + "another process may be using port 8765"
            ) from exc
        self._code: str | None = None
        self._error: ConnectError | None = None
        self._closed: bool = False

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self) -> "CallbackListener":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.server_close()

    def wait(self, timeout: float = CALLBACK_TIMEOUT_SECONDS) -> str:
        deadline = time.monotonic() + timeout
        while self._code is None and self._error is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConnectError("Timed out waiting for Devin authorization")
            self._server.timeout = min(remaining, 0.25)
            self._server.handle_request()

        if self._error is not None:
            raise self._error
        assert self._code is not None
        return self._code

    def _handle_request(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if parsed.path != "/callback":
            self._send_html(handler, 404, "Not found.")
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        errors = query.get("error", [])
        if errors and errors[0].strip():
            descriptions = query.get("error_description", [])
            description = descriptions[0] if descriptions else errors[0]
            self._error = ConnectError(
                f"Devin authorization failed: {_sanitize_remote_description(description)}"
            )
            self._send_html(
                handler,
                400,
                "Devin authorization failed. Return to your terminal for details.",
            )
            return

        codes = query.get("code", [])
        if len(codes) != 1 or not codes[0].strip():
            self._send_html(handler, 400, "Missing or invalid authorization code.")
            return

        self._code = codes[0]
        self._send_html(
            handler,
            200,
            "Authorization received. Return to your terminal to finish setup.",
        )

    @staticmethod
    def _send_html(
        handler: http.server.BaseHTTPRequestHandler, status: int, message: str
    ) -> None:
        body = (
            "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
            f"<title>Devin Outposts</title><body><p>{message}</p></body></html>"
        ).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        _ = handler.wfile.write(body)


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_connect_url(code_challenge: str, outpost_name: str, platform: str) -> str:
    query = urlencode(
        {
            "callback_url": CALLBACK_URL,
            "outpost_name": outpost_name,
            "platform": platform,
            "code_challenge": code_challenge,
        }
    )
    return f"{CONNECT_URL}?{query}"


def exchange_code(
    code: str,
    code_verifier: str,
    client: httpx.Client | None = None,
) -> ConnectionCredentials:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
    }
    owns_client = client is None
    request_client = client or httpx.Client(timeout=30.0)
    try:
        try:
            response = request_client.post(TOKEN_URL, data=form)
        except httpx.RequestError as exc:
            raise ConnectError("Could not reach Devin's connection-token endpoint") from exc
    finally:
        if owns_client:
            request_client.close()

    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code == 400:
            payload = _json_mapping(response)
            description = payload.get("error_description") if payload is not None else None
            if isinstance(description, str) and description.strip():
                response_token = payload.get("access_token")
                secrets_to_redact = [code, code_verifier]
                if isinstance(response_token, str):
                    secrets_to_redact.append(response_token)
                raise ConnectError(
                    "Devin authorization failed: "
                    + _sanitize_remote_description(description, secrets_to_redact)
                )
        raise ConnectError(
            f"Devin connection-token endpoint returned HTTP {response.status_code}"
        )

    payload = _json_mapping(response)
    if payload is None:
        raise ConnectError("Devin connection-token endpoint returned invalid JSON")

    outpost_id = _required_string(payload, "outpost_id")
    access_token = _required_string(payload, "access_token")
    api_base_url = normalize_devin_api_url(_required_string(payload, "api_base_url"))
    outpost_name_value = payload.get("outpost_name")
    outpost_name = outpost_name_value.strip() if isinstance(outpost_name_value, str) else None
    if outpost_name == "":
        outpost_name = None
    return ConnectionCredentials(
        outpost_id=outpost_id,
        access_token=access_token,
        api_base_url=api_base_url,
        outpost_name=outpost_name,
    )


def update_env_file(
    path: Path,
    credentials: ConnectionCredentials,
    *,
    force: bool = False,
) -> None:
    _ensure_env_can_be_updated(path, force=force)
    values = {
        "DEVIN_OUTPOSTS_TOKEN": credentials.access_token,
        "DEVIN_API_URL": normalize_devin_api_url(credentials.api_base_url),
        "OUTPOST_ID": credentials.outpost_id,
    }
    for value in values.values():
        if "\r" in value or "\n" in value:
            raise ConnectError("Devin returned a credential containing a newline")

    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise ConnectError(f"Could not read target env file {path}") from exc

    rendered = _render_env(existing, values)
    _atomic_write_secret(path, rendered)


def _ensure_env_can_be_updated(path: Path, *, force: bool) -> None:
    if force or not path.exists():
        return
    try:
        configured = dotenv_values(path)
    except (OSError, ValueError) as exc:
        raise ConnectError(f"Could not read target env file {path}") from exc

    for key in ("DEVIN_OUTPOSTS_TOKEN", "OUTPOST_ID"):
        value = configured.get(key)
        if value and value != _PLACEHOLDERS[key]:
            raise ConnectError(
                "The target env file is already configured; pass --force to replace "
                + "its Devin outpost credentials, or --env-file to write a second outpost's "
                + "credentials to another file"
            )


def _render_env(existing: str, values: Mapping[str, str]) -> str:
    output: list[str] = []
    written: set[str] = set()
    for line in existing.splitlines(keepends=True):
        match = _ENV_ASSIGNMENT.match(line)
        if match is None:
            output.append(line)
            continue
        key = match.group(1)
        if key in written:
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n"
        output.append(f"{key}={_encode_env_value(values[key])}{newline}")
        written.add(key)

    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += "\n"
    for key in _MANAGED_ENV_KEYS:
        if key not in written:
            output.append(f"{key}={_encode_env_value(values[key])}\n")
    return "".join(output)


def _encode_env_value(value: str) -> str:
    if _SAFE_UNQUOTED_ENV_VALUE.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _atomic_write_secret(path: Path, content: str) -> None:
    parent = path.parent
    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            _ = handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        if os.name == "posix":
            os.chmod(path, 0o600)
    except OSError as exc:
        if temporary_path is not None:
            try:
                _ = temporary_path.unlink()
            except OSError:
                pass
        raise ConnectError(
            f"Devin credentials were created but could not be saved to {path}"
        ) from exc


def _json_mapping(response: httpx.Response) -> Mapping[str, object] | None:
    try:
        value: object = response.json()
    except ValueError:
        return None
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectError(
            f"Devin connection-token response is missing required field {field}"
        )
    return value


def _sanitize_remote_description(
    value: str, secrets_to_redact: Sequence[str] = ()
) -> str:
    sanitized = _CONTROL_CHARACTERS.sub(" ", value).strip()
    for secret in secrets_to_redact:
        if secret:
            sanitized = sanitized.replace(secret, "<redacted>")
    return sanitized[:300] or "Authorization was denied"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outposts-connect",
        description="Connect a Devin outpost and write its credentials to .env.",
    )
    parser.add_argument("--platform", choices=("linux", "windows"), default="linux")
    parser.add_argument("--outpost-name")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    outpost_name = (args.outpost_name or f"daytona-{args.platform}").strip()
    if not outpost_name:
        parser.error("--outpost-name cannot be empty")

    try:
        _ensure_env_can_be_updated(args.env_file, force=args.force)
        verifier, challenge = generate_pkce()
        url = build_connect_url(challenge, outpost_name, args.platform)
        with CallbackListener() as listener:
            print(f"Open this URL to connect Devin:\n{url}")
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False
            if not opened:
                print("A browser could not be opened automatically; open the URL above.")
            code = listener.wait()

        credentials = exchange_code(code, verifier)
        update_env_file(args.env_file, credentials, force=args.force)
    except KeyboardInterrupt:
        print("Connection cancelled.", file=sys.stderr)
        return 130
    except ConnectError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Connected outpost: {credentials.outpost_name or outpost_name}")
    print(f"Outpost ID: {credentials.outpost_id}")
    print(f"Devin API: {credentials.api_base_url}")
    print(f"Credentials saved to: {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
