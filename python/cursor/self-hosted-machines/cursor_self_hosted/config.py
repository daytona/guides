"""Parse the controller spawn environment."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

DEFAULT_IDLE_RELEASE_TIMEOUT_SECONDS = 900
DEFAULT_MONITOR_POLL_SECONDS = 5.0
DEFAULT_SANDBOX_CREATE_TIMEOUT_SECONDS = 120
DEFAULT_SANDBOX_LAUNCH_TIMEOUT_SECONDS = 60
WORKER_DIRECTORY = "/home/daytona/workspace"
LINUX_CHECKOUT_HOOK_PATH = "/usr/local/bin/cursor-self-hosted-checkout"


class ConfigError(RuntimeError):
    """Raised when the controller environment is missing or invalid."""


@dataclass(frozen=True)
class Config:
    daytona_api_key: str
    daytona_target: str | None
    snapshot_name: str
    cursor_api_key: str
    cursor_agent_worker_id: str
    cursor_pool: str
    cursor_request_id: str
    cursor_repo_url: str | None
    cursor_repo_urls: tuple[str, ...]
    cursor_worker_name: str | None
    cursor_api_url: str | None
    cursor_api_endpoint: str | None
    idle_release_timeout_seconds: int
    monitor_poll_seconds: float
    sandbox_create_timeout_seconds: int
    sandbox_launch_timeout_seconds: int

    @classmethod
    def from_env(cls, environment: Mapping[str, str]) -> Config:
        required = {
            name: _optional_value(environment, name)
            for name in (
                "DAYTONA_API_KEY",
                "SNAPSHOT_NAME",
                "CURSOR_API_KEY",
                "CURSOR_AGENT_WORKER_ID",
                "CURSOR_POOL",
                "CURSOR_REQUEST_ID",
            )
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ConfigError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        cursor_repo_url = _optional_value(environment, "CURSOR_REPO_URL")
        cursor_repo_urls = _parse_repo_urls(
            _optional_value(environment, "CURSOR_REPO_URLS"),
            cursor_repo_url,
        )

        return cls(
            daytona_api_key=cast(str, required["DAYTONA_API_KEY"]),
            daytona_target=_optional_value(environment, "DAYTONA_TARGET"),
            snapshot_name=cast(str, required["SNAPSHOT_NAME"]),
            cursor_api_key=cast(str, required["CURSOR_API_KEY"]),
            cursor_agent_worker_id=cast(
                str, required["CURSOR_AGENT_WORKER_ID"]
            ),
            cursor_pool=cast(str, required["CURSOR_POOL"]),
            cursor_request_id=cast(str, required["CURSOR_REQUEST_ID"]),
            cursor_repo_url=cursor_repo_url,
            cursor_repo_urls=cursor_repo_urls,
            cursor_worker_name=_optional_value(
                environment, "CURSOR_WORKER_NAME"
            ),
            cursor_api_url=_optional_value(environment, "CURSOR_API_URL"),
            cursor_api_endpoint=_optional_value(
                environment, "CURSOR_API_ENDPOINT"
            ),
            idle_release_timeout_seconds=_parse_positive_int(
                environment,
                "CURSOR_WORKER_IDLE_RELEASE_TIMEOUT",
                DEFAULT_IDLE_RELEASE_TIMEOUT_SECONDS,
            ),
            monitor_poll_seconds=_parse_positive_float(
                environment,
                "MONITOR_POLL_SECONDS",
                DEFAULT_MONITOR_POLL_SECONDS,
            ),
            sandbox_create_timeout_seconds=_parse_positive_int(
                environment,
                "SANDBOX_CREATE_TIMEOUT_SECONDS",
                DEFAULT_SANDBOX_CREATE_TIMEOUT_SECONDS,
            ),
            sandbox_launch_timeout_seconds=_parse_positive_int(
                environment,
                "SANDBOX_LAUNCH_TIMEOUT_SECONDS",
                DEFAULT_SANDBOX_LAUNCH_TIMEOUT_SECONDS,
            ),
        )


def sandbox_name_for(worker_id: str) -> str:
    direct_name = f"cursor-{worker_id}"
    if len(direct_name) <= 63 and re.fullmatch(
        r"worker-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", worker_id
    ):
        return direct_name

    digest = hashlib.sha256(worker_id.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", worker_id.lower()).strip("-")
    slug = (slug or "worker")[:43].rstrip("-")
    return f"cursor-{slug}-{digest}"


def sandbox_labels(config: Config, sandbox_class: str) -> dict[str, str]:
    return {
        "cursor.worker_id": config.cursor_agent_worker_id,
        "cursor.request_id": config.cursor_request_id,
        "cursor.pool": config.cursor_pool,
        "cursor.sandbox_class": sandbox_class,
    }


def worker_environment(config: Config) -> dict[str, str]:
    values = {
        "CURSOR_API_KEY": config.cursor_api_key,
        "CURSOR_AGENT_WORKER_ID": config.cursor_agent_worker_id,
        "CURSOR_WORKER_NAME": config.cursor_worker_name,
    }
    return {name: value for name, value in values.items() if value}


def worker_command(config: Config) -> list[str]:
    command = [
        "/usr/local/bin/agent",
        "worker",
        "--pool",
        config.cursor_pool,
        "--worker-dir",
        WORKER_DIRECTORY,
        "--management-addr",
        "0.0.0.0:8080",
    ]
    if config.cursor_repo_urls:
        command.extend(
            [
                "--mint-github-token",
                "--on-session-start",
                LINUX_CHECKOUT_HOOK_PATH,
            ]
        )
    command.extend(
        [
            "--idle-release-timeout",
            str(config.idle_release_timeout_seconds),
            "start",
        ]
    )
    return command


def primary_origin_url(config: Config) -> str | None:
    """Return the HTTPS origin the worker workspace advertises to Cursor.

    Cursor only routes a repository request to a worker whose workspace has
    that repository as `origin`, so the spawn command seeds it before the
    worker starts. Cursor sends repository URLs without a scheme.
    """
    if not config.cursor_repo_urls:
        return None
    url = config.cursor_repo_urls[0].strip()
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ConfigError(
            "CURSOR_REPO_URL must be a credential-free HTTPS repository URL"
        )
    return url


def redact(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    ordered_secrets = sorted(
        {secret for secret in secrets if secret}, key=len, reverse=True
    )
    for secret in ordered_secrets:
        redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _optional_value(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    value = environment.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_repo_urls(
    value: str | None,
    fallback: str | None,
) -> tuple[str, ...]:
    if value is None:
        return (fallback,) if fallback is not None else ()
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConfigError(
            "CURSOR_REPO_URLS must be a JSON array of strings"
        ) from exc
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise ConfigError("CURSOR_REPO_URLS must be a JSON array of strings")
    return tuple(item.strip() for item in parsed)


def _parse_positive_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    value = _optional_value(environment, name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(
            f"{name} must be a positive integer; got {value!r}"
        ) from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer; got {value!r}")
    return parsed


def _parse_positive_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    value = _optional_value(environment, name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(
            f"{name} must be a positive number; got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigError(f"{name} must be a positive number; got {value!r}")
    return parsed
