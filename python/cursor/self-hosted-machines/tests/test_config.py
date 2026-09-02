from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any, cast

import pytest

from cursor_self_hosted.config import (
    Config,
    ConfigError,
    redact,
    sandbox_labels,
    sandbox_name_for,
    worker_command,
    worker_environment,
)


REQUIRED_NAMES = (
    "CURSOR_AGENT_WORKER_ID",
    "CURSOR_API_KEY",
    "CURSOR_POOL",
    "CURSOR_REQUEST_ID",
    "DAYTONA_API_KEY",
    "SNAPSHOT_NAME",
)


def config_from_env(env: dict[str, str]):
    return Config.from_env(env)


def test_missing_required_environment_names_are_sorted_and_actionable() -> None:
    with pytest.raises(ConfigError) as caught:
        Config.from_env({})

    assert str(caught.value) == (
        "Missing required environment variables: " + ", ".join(REQUIRED_NAMES)
    )


def test_whitespace_only_required_values_are_missing(
    valid_env: dict[str, str],
) -> None:
    env = {
        **valid_env,
        "DAYTONA_API_KEY": " \t ",
        "SNAPSHOT_NAME": "\r\n",
        "CURSOR_API_KEY": "   ",
    }

    with pytest.raises(ConfigError) as caught:
        config_from_env(env)

    assert str(caught.value) == (
        "Missing required environment variables: "
        "CURSOR_API_KEY, DAYTONA_API_KEY, SNAPSHOT_NAME"
    )


def test_environment_values_are_trimmed_without_mutating_the_input() -> None:
    env = {
        "DAYTONA_API_KEY": "  daytona-key-test  ",
        "SNAPSHOT_NAME": "  snapshot-test  ",
        "CURSOR_API_KEY": "  cursor-key-test  ",
        "CURSOR_AGENT_WORKER_ID": "  worker-123  ",
        "CURSOR_POOL": "  pool-test  ",
        "CURSOR_REQUEST_ID": "  request-456  ",
        "CURSOR_WORKER_NAME": " \t ",
        "CURSOR_REPO_URLS": (
            ' [ "https://example.test/acme/one.git", '
            '"https://example.test/acme/two.git" ] '
        ),
    }
    original = env.copy()

    config = config_from_env(env)

    assert config.daytona_api_key == "daytona-key-test"
    assert config.snapshot_name == "snapshot-test"
    assert config.cursor_api_key == "cursor-key-test"
    assert config.cursor_agent_worker_id == "worker-123"
    assert config.cursor_pool == "pool-test"
    assert config.cursor_request_id == "request-456"
    assert config.cursor_worker_name is None
    assert config.cursor_repo_urls == (
        "https://example.test/acme/one.git",
        "https://example.test/acme/two.git",
    )
    assert env == original


def test_daytona_target_is_trimmed_and_optional(
    valid_env: dict[str, str],
) -> None:
    targeted = config_from_env(
        {**valid_env, "DAYTONA_TARGET": "  eu-central-1  "}
    )
    defaulted = config_from_env(valid_env)

    assert targeted.daytona_target == "eu-central-1"
    assert defaulted.daytona_target is None


@pytest.mark.parametrize(
    "value",
    [
        "not-json",
        '{"url": "https://example.test/acme/one.git"}',
    ],
)
def test_cursor_repo_urls_rejects_malformed_json_or_non_array(
    valid_env: dict[str, str], value: str
) -> None:
    with pytest.raises(ConfigError) as caught:
        config_from_env({**valid_env, "CURSOR_REPO_URLS": value})

    assert "CURSOR_REPO_URLS must be a JSON array of strings" in str(caught.value)


def test_cursor_repo_urls_rejects_non_string_entries(
    valid_env: dict[str, str],
) -> None:
    with pytest.raises(ConfigError) as caught:
        config_from_env(
            {
                **valid_env,
                "CURSOR_REPO_URLS": (
                    '["https://example.test/acme/one.git", 7]'
                ),
            }
        )

    assert "CURSOR_REPO_URLS must be a JSON array of strings" in str(caught.value)


def test_cursor_repo_url_is_used_when_plural_list_is_absent(
    valid_env: dict[str, str],
) -> None:
    config = config_from_env(
        {
            **valid_env,
            "CURSOR_REPO_URL": "  https://example.test/acme/fallback.git  ",
        }
    )

    assert config.cursor_repo_url == "https://example.test/acme/fallback.git"
    assert config.cursor_repo_urls == (
        "https://example.test/acme/fallback.git",
    )


def test_explicit_environment_mapping_does_not_mutate_process_environment(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in REQUIRED_NAMES:
        monkeypatch.delenv(name, raising=False)

    config_from_env(valid_env)

    assert all(name not in os.environ for name in REQUIRED_NAMES)


def test_timeout_text_is_converted_to_positive_numeric_fields(
    valid_env: dict[str, str],
) -> None:
    config = config_from_env(
        {
            **valid_env,
            "CURSOR_WORKER_IDLE_RELEASE_TIMEOUT": " 900 ",
            "MONITOR_POLL_SECONDS": " 2.5 ",
            "SANDBOX_CREATE_TIMEOUT_SECONDS": " 45 ",
            "SANDBOX_LAUNCH_TIMEOUT_SECONDS": " 60 ",
        }
    )

    assert config.idle_release_timeout_seconds == 900
    assert type(config.idle_release_timeout_seconds) is int
    assert config.monitor_poll_seconds == 2.5
    assert type(config.monitor_poll_seconds) is float
    assert config.sandbox_create_timeout_seconds == 45
    assert type(config.sandbox_create_timeout_seconds) is int
    assert config.sandbox_launch_timeout_seconds == 60
    assert type(config.sandbox_launch_timeout_seconds) is int


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CURSOR_WORKER_IDLE_RELEASE_TIMEOUT", "0"),
        ("MONITOR_POLL_SECONDS", "-0.5"),
        ("MONITOR_POLL_SECONDS", "nan"),
        ("MONITOR_POLL_SECONDS", "inf"),
        ("MONITOR_POLL_SECONDS", "-inf"),
        ("SANDBOX_CREATE_TIMEOUT_SECONDS", "0"),
        ("SANDBOX_CREATE_TIMEOUT_SECONDS", "45.5"),
        ("SANDBOX_CREATE_TIMEOUT_SECONDS", "not-an-integer"),
        ("SANDBOX_LAUNCH_TIMEOUT_SECONDS", "-1"),
        ("SANDBOX_LAUNCH_TIMEOUT_SECONDS", "60.5"),
        ("SANDBOX_LAUNCH_TIMEOUT_SECONDS", "not-an-integer"),
    ],
)
def test_invalid_timeout_values_raise_config_error(
    valid_env: dict[str, str], name: str, value: str
) -> None:
    with pytest.raises(ConfigError) as caught:
        config_from_env({**valid_env, name: value})

    message = str(caught.value)
    assert name in message
    assert "positive" in message.lower()
    assert value in message


def test_sandbox_names_are_deterministic_bounded_safe_and_collision_resistant() -> None:
    slash_name = sandbox_name_for("a/b")
    hyphen_name = sandbox_name_for("a-b")
    long_name = sandbox_name_for("Worker/" + "x" * 500)

    assert slash_name == sandbox_name_for("a/b")
    assert slash_name.startswith("cursor-a-b-")
    assert hyphen_name.startswith("cursor-a-b-")
    assert slash_name != hyphen_name
    assert len(long_name) <= 63
    assert re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", long_name)


def test_sandbox_labels_contain_exact_claim_identity() -> None:
    config = SimpleNamespace(
        cursor_agent_worker_id="worker-123",
        cursor_request_id="request-456",
        cursor_pool="pool-test",
    )

    assert sandbox_labels(cast(Any, config), "linux-vm") == {
        "cursor.worker_id": "worker-123",
        "cursor.request_id": "request-456",
        "cursor.pool": "pool-test",
        "cursor.sandbox_class": "linux-vm",
    }


@pytest.mark.parametrize(
    ("worker_name", "expected_environment"),
    [
        (
            "worker-test",
            {
                "CURSOR_API_KEY": "cursor-key-test",
                "CURSOR_AGENT_WORKER_ID": "worker-123",
                "CURSOR_WORKER_NAME": "worker-test",
            },
        ),
        (
            None,
            {
                "CURSOR_API_KEY": "cursor-key-test",
                "CURSOR_AGENT_WORKER_ID": "worker-123",
            },
        ),
    ],
)
def test_worker_environment_contains_only_worker_credentials_and_optional_name(
    worker_name: str | None,
    expected_environment: dict[str, str],
) -> None:
    config = SimpleNamespace(
        daytona_api_key="host-only-daytona-key-test",
        snapshot_name="host-only-snapshot",
        cursor_api_key="cursor-key-test",
        cursor_agent_worker_id="worker-123",
        cursor_pool="pool-test",
        cursor_request_id="request-456",
        cursor_worker_name=worker_name,
        cursor_api_url="https://api.example.test",
        cursor_api_endpoint="https://endpoint.example.test",
        cursor_repo_url="https://example.test/acme/one.git",
        cursor_repo_urls=(
            "https://example.test/acme/one.git",
            "https://example.test/acme/two.git",
        ),
    )

    environment = worker_environment(cast(Any, config))

    assert environment == expected_environment
    assert {
        "DAYTONA_API_KEY",
        "SNAPSHOT_NAME",
        "CURSOR_POOL",
        "CURSOR_REQUEST_ID",
        "CURSOR_API_URL",
        "CURSOR_API_ENDPOINT",
        "CURSOR_REPO_URL",
        "CURSOR_REPO_URLS",
    }.isdisjoint(environment)


def test_worker_command_with_repositories_mints_token_and_runs_clone_hook() -> None:
    config = SimpleNamespace(
        cursor_pool="pool-test",
        cursor_repo_urls=(
            "https://example.test/acme/one.git",
            "https://example.test/acme/two.git",
        ),
        idle_release_timeout_seconds=900,
    )

    command = worker_command(cast(Any, config))

    assert command == [
        "/usr/local/bin/agent",
        "worker",
        "--pool",
        "pool-test",
        "--worker-dir",
        "/home/daytona/workspace",
        "--management-addr",
        "0.0.0.0:8080",
        "--mint-github-token",
        "--on-session-start",
        "/usr/local/bin/clone-cursor-self-hosted-repos",
        "--idle-release-timeout",
        "900",
        "start",
    ]
    assert "--clone-git-repos" not in command


def test_worker_command_without_repositories_omits_repository_flags() -> None:
    config = SimpleNamespace(
        cursor_pool="pool-test",
        cursor_repo_urls=(),
        idle_release_timeout_seconds=900,
    )

    command = worker_command(cast(Any, config))

    assert command == [
        "/usr/local/bin/agent",
        "worker",
        "--pool",
        "pool-test",
        "--worker-dir",
        "/home/daytona/workspace",
        "--management-addr",
        "0.0.0.0:8080",
        "--idle-release-timeout",
        "900",
        "start",
    ]
    assert {
        "--clone-git-repos",
        "--mint-github-token",
        "--on-session-start",
    }.isdisjoint(command)


def test_redaction_replaces_all_secrets_longest_first() -> None:
    redacted = redact(
        "cursor-secret-long then cursor-secret and daytona-secret",
        ("", "cursor-secret", "daytona-secret", "cursor-secret-long"),
    )

    assert redacted == "<redacted> then <redacted> and <redacted>"
