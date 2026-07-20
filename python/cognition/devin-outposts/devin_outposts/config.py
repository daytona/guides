"""Define the environment contract for Devin Outposts orchestration.

``DEVIN_OUTPOSTS_TOKEN`` is the machine-serving token read by the Devin worker
when ``--token`` is omitted; it is not interchangeable with a generic
``DEVIN_API_TOKEN``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, cast

LOGGER = logging.getLogger(__name__)

DEFAULT_DEVIN_API_URL = "https://api.devin.ai"
DEFAULT_STATE_DIR = "~/.devin-outposts-orchestrator"
DEFAULT_WORKDIR = "/home/daytona/workspace"
DEFAULT_DEVIN_CHROME_PATH = "/usr/bin/chromium"
DEFAULT_MAX_CONCURRENT_SESSIONS = 5
DEFAULT_WORKER_POLL_SECONDS = 5.0
DEFAULT_WATCH_RECONNECT_SECONDS = 3.0
DEFAULT_JANITOR_INTERVAL_SECONDS = 60.0
DEFAULT_PENDING_POLL_SECONDS = 15.0
DEFAULT_WINDOWS_WORKDIR = r"C:\repos"
DEFAULT_WINDOWS_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class RepoSpec:
    url: str
    target_name: str


@dataclass(frozen=True)
class Config:
    devin_outposts_token: str
    devin_api_url: str
    outpost_id: str
    snapshot_name: str
    max_concurrent_sessions: int
    state_dir: Path
    acceptor_id: str
    workdir: str
    devin_chrome_path: str
    repos: tuple[RepoSpec, ...]
    git_username: str | None
    git_token: str | None
    windows_workdir: str = DEFAULT_WINDOWS_WORKDIR
    windows_chrome_path: str = DEFAULT_WINDOWS_CHROME_PATH
    worker_poll_seconds: float = DEFAULT_WORKER_POLL_SECONDS
    watch_reconnect_seconds: float = DEFAULT_WATCH_RECONNECT_SECONDS
    janitor_interval_seconds: float = DEFAULT_JANITOR_INTERVAL_SECONDS
    pending_poll_seconds: float = DEFAULT_PENDING_POLL_SECONDS

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv_if_available()

        required = {
            "DEVIN_OUTPOSTS_TOKEN": _empty_to_none(_env("DEVIN_OUTPOSTS_TOKEN")),
            "DAYTONA_API_KEY": _empty_to_none(_env("DAYTONA_API_KEY")),
            "OUTPOST_ID": _empty_to_none(_env("OUTPOST_ID")),
            "SNAPSHOT_NAME": _empty_to_none(_env("SNAPSHOT_NAME")),
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ConfigError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        devin_outposts_token = cast(str, required["DEVIN_OUTPOSTS_TOKEN"])
        outpost_id = cast(str, required["OUTPOST_ID"])
        snapshot_name = cast(str, required["SNAPSHOT_NAME"])

        state_dir = Path(_env("STATE_DIR", DEFAULT_STATE_DIR)).expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)

        acceptor_id = resolve_acceptor_id(
            state_dir,
            outpost_id,
            _empty_to_none(_env("ACCEPTOR_ID")),
        )

        max_concurrent = _parse_positive_int(
            _env("MAX_CONCURRENT_SESSIONS"),
            DEFAULT_MAX_CONCURRENT_SESSIONS,
            "MAX_CONCURRENT_SESSIONS",
        )

        api_url = normalize_devin_api_url(_env("DEVIN_API_URL", DEFAULT_DEVIN_API_URL))
        workdir = _env("WORKDIR", DEFAULT_WORKDIR).rstrip("/") or DEFAULT_WORKDIR
        chrome_path = _env("DEVIN_CHROME_PATH", DEFAULT_DEVIN_CHROME_PATH)
        windows_workdir = (
            _env("WINDOWS_WORKDIR", DEFAULT_WINDOWS_WORKDIR) or DEFAULT_WINDOWS_WORKDIR
        )
        windows_chrome_path = _env(
            "DEVIN_WINDOWS_CHROME_PATH", DEFAULT_WINDOWS_CHROME_PATH
        )
        git_username = _empty_to_none(_env("GIT_USERNAME"))
        git_token = _empty_to_none(_env("GIT_TOKEN"))

        return cls(
            devin_outposts_token=devin_outposts_token,
            devin_api_url=api_url,
            outpost_id=outpost_id,
            snapshot_name=snapshot_name,
            max_concurrent_sessions=max_concurrent,
            state_dir=state_dir,
            acceptor_id=acceptor_id,
            workdir=workdir,
            devin_chrome_path=chrome_path,
            repos=parse_repos(_env("REPOS")),
            git_username=git_username,
            git_token=git_token,
            windows_workdir=windows_workdir,
            windows_chrome_path=windows_chrome_path,
        )

    def redacted(self, value: object) -> str:
        return redact(str(value), self.secrets_for_redaction())

    def secrets_for_redaction(self) -> tuple[str, ...]:
        values = [
            self.devin_outposts_token,
            self.git_token,
            os.environ.get("DAYTONA_API_KEY"),
        ]
        return tuple(value for value in values if value)

    def workdir_for(self, platform: str) -> str:
        return self.windows_workdir if platform == "windows" else self.workdir

    def chrome_path_for(self, platform: str) -> str:
        return (
            self.windows_chrome_path
            if platform == "windows"
            else self.devin_chrome_path
        )


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(".env")


def resolve_acceptor_id(state_dir: Path, outpost_id: str, configured: str | None) -> str:
    outpost_key = hashlib.sha256(outpost_id.encode("utf-8")).hexdigest()
    path = state_dir / "outposts" / outpost_key / "acceptor_id"
    if configured:
        configured = configured.strip()
        if configured:
            atomic_write_text(path, configured + "\n")
            return configured
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    generated = "devin-outposts-" + uuid.uuid4().hex
    atomic_write_text(path, generated + "\n")
    return generated


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def parse_repos(value: str | None) -> tuple[RepoSpec, ...]:
    if not value:
        return ()
    repos: list[RepoSpec] = []
    used_names: set[str] = set()
    for raw_url in value.split(","):
        url = raw_url.strip()
        if not url:
            continue
        name = repo_target_name(url)
        base_name = name
        suffix = 2
        while name in used_names:
            name = f"{base_name}-{suffix}"
            suffix += 1
        used_names.add(name)
        repos.append(RepoSpec(url=url, target_name=name))
    return tuple(repos)


def repo_target_name(url: str) -> str:
    without_query = url.split("?", 1)[0].rstrip("/")
    tail = without_query.rsplit("/", 1)[-1]
    if ":" in tail and not tail.endswith(".git"):
        tail = tail.rsplit(":", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", tail).strip("-._")
    return cleaned or "repo"


def normalize_devin_api_url(value: str) -> str:
    url = value.rstrip("/")
    if url.endswith("/opbeta"):
        url = url[: -len("/opbeta")]
    return url


def redact(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in sorted(
        (secret for secret in secrets if secret), key=len, reverse=True
    ):
        redacted = redacted.replace(secret, "<redacted>")
    redacted = re.sub(r"(https?://)([^/\s:@]+):([^@\s/]+)@", r"\1<redacted>@", redacted)
    return redacted


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_positive_int(value: str | None, default: int, name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ConfigError(f"{name} must be at least 1")
    return parsed
