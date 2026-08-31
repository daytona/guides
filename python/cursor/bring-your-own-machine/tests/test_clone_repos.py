from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cursor_byom import clone_repos as clone_repos_module
from cursor_byom.clone_repos import (
    HookError,
    Repo,
    clone_repositories,
    main,
    repos_from_payload,
    target_name,
)


@dataclass(frozen=True)
class RunCall:
    command: tuple[str, ...]
    kwargs: dict[str, Any]


class ScriptedRun:
    def __init__(self, effects: Sequence[BaseException | None] = ()) -> None:
        self._effects = iter(effects)
        self.calls: list[RunCall] = []

    def __call__(
        self,
        command: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        self.calls.append(RunCall(normalized, kwargs))
        effect = next(self._effects, None)
        if effect is not None:
            raise effect
        return subprocess.CompletedProcess(normalized, 0, "", "")


def test_repos_from_payload_prefers_structured_repos_and_preserves_optional_refs() -> None:
    payload = {
        "repo_urls": [
            "https://github.com/acme/payments",
            "https://github.com/acme/catalog",
        ],
        "repos": [
            {
                "repo_url": "https://github.com/acme/payments",
                "ref": "main",
                "primary": True,
            },
            {
                "repo_url": "https://github.com/acme/catalog",
                "primary": False,
            },
        ],
    }

    repos = repos_from_payload(payload)

    assert repos == (
        Repo(url="https://github.com/acme/payments", ref="main"),
        Repo(url="https://github.com/acme/catalog", ref=None),
    )


def test_repos_from_payload_uses_repo_urls_when_structured_repos_are_absent() -> None:
    repos = repos_from_payload(
        {
            "repo_urls": [
                "https://github.com/acme/payments",
                "https://github.com/acme/catalog.git",
            ]
        }
    )

    assert repos == (
        Repo(url="https://github.com/acme/payments", ref=None),
        Repo(url="https://github.com/acme/catalog.git", ref=None),
    )


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (None, "payload"),
        ([], "payload"),
        ({"repos": "https://github.com/acme/payments"}, "repos"),
        ({"repos": ["https://github.com/acme/payments"]}, "repos"),
        ({"repos": [{}]}, "repo_url"),
        ({"repos": [{"repo_url": ""}]}, "repo_url"),
        (
            {
                "repos": [
                    {
                        "repo_url": "https://github.com/acme/payments",
                        "ref": 17,
                    }
                ]
            },
            "ref",
        ),
        ({"repo_urls": "https://github.com/acme/payments"}, "repo_urls"),
        (
            {
                "repo_urls": [
                    "https://github.com/acme/payments",
                    None,
                ]
            },
            "repo_urls",
        ),
    ],
)
def test_repos_from_payload_rejects_malformed_repository_metadata(
    payload: object,
    field: str,
) -> None:
    with pytest.raises(HookError) as caught:
        repos_from_payload(payload)

    assert field in str(caught.value)


def test_target_name_is_deterministic_safe_and_unique_for_equal_basenames() -> None:
    first_url = "https://github.com/acme/api.git"
    second_url = "https://gitlab.example.test/other/api.git"

    first = target_name(first_url)
    second = target_name(second_url)

    assert target_name(first_url) == first
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", first)
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", second)
    assert first not in {".", ".."}
    assert second not in {".", ".."}


def test_target_name_does_not_allow_url_path_traversal() -> None:
    name = target_name("https://example.test/acme/../../private/.git")

    assert "/" not in name
    assert "\\" not in name
    assert ".." not in name
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)


def test_clone_repositories_clones_into_workspace_and_checks_out_ref(
    tmp_path: Path,
) -> None:
    ref = "0123456789abcdef0123456789abcdef01234567"
    url = "https://github.com/acme/payments.git"
    run = ScriptedRun()
    destination = tmp_path / target_name(url)

    clone_repositories(
        {"repos": [{"repo_url": url, "ref": ref, "primary": True}]},
        tmp_path,
        run=run,
        sleep=lambda _: None,
    )

    assert [call.command for call in run.calls] == [
        ("git", "clone", "--", url, str(destination)),
        ("git", "-C", str(destination), "checkout", "--detach", ref),
    ]
    assert all(call.kwargs.get("check") is True for call in run.calls)


def test_checkout_failure_removes_clone_and_raises_sanitized_error(
    tmp_path: Path,
) -> None:
    url = "https://github.com/acme/payments.git"
    ref = "missing-private-ref"
    sensitive_detail = "credential-marker-not-a-real-secret"
    destination = tmp_path / target_name(url)
    attempted_commands: list[tuple[str, ...]] = []

    def clone_then_fail_checkout(
        command: Sequence[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        attempted_commands.append(normalized)
        if normalized[:3] == ("git", "clone", "--"):
            (destination / ".git").mkdir(parents=True)
            (destination / "untrusted-state").write_text(
                "must be removed",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(normalized, 0, "", "")
        raise subprocess.CalledProcessError(
            128,
            normalized,
            stderr=f"fatal: checkout exposed {sensitive_detail}",
        )

    with pytest.raises(HookError) as caught:
        clone_repositories(
            {"repos": [{"repo_url": url, "ref": ref, "primary": True}]},
            tmp_path,
            run=clone_then_fail_checkout,
            sleep=lambda _: None,
        )

    assert attempted_commands == [
        ("git", "clone", "--", url, str(destination)),
        ("git", "-C", str(destination), "checkout", "--detach", ref),
    ]
    message = str(caught.value)
    assert "checkout" in message.lower()
    assert ref not in message
    assert sensitive_detail not in message
    assert not destination.exists()


def test_symlink_destination_is_unlinked_before_clone(tmp_path: Path) -> None:
    url = "https://github.com/acme/payments.git"
    destination = tmp_path / target_name(url)
    symlink_target = tmp_path / "attacker-controlled"
    (symlink_target / ".git").mkdir(parents=True)
    sentinel = symlink_target / "must-not-be-removed"
    sentinel.write_text("outside destination", encoding="utf-8")
    destination.symlink_to(symlink_target, target_is_directory=True)
    attempted_commands: list[tuple[str, ...]] = []

    def clone_after_unlink(
        command: Sequence[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        attempted_commands.append(normalized)
        assert not destination.is_symlink()
        assert not destination.exists()
        (destination / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(normalized, 0, "", "")

    clone_repositories(
        {"repo_urls": [url]},
        tmp_path,
        run=clone_after_unlink,
        sleep=lambda _: None,
    )

    assert attempted_commands == [
        ("git", "clone", "--", url, str(destination)),
    ]
    assert destination.is_dir()
    assert not destination.is_symlink()
    assert (destination / ".git").is_dir()
    assert sentinel.read_text(encoding="utf-8") == "outside destination"


def test_existing_git_repository_is_left_untouched(tmp_path: Path) -> None:
    url = "https://github.com/acme/payments.git"
    destination = tmp_path / target_name(url)
    (destination / ".git").mkdir(parents=True)
    run = ScriptedRun()
    sleeps: list[float] = []

    clone_repositories(
        {"repo_urls": [url]},
        tmp_path,
        run=run,
        sleep=sleeps.append,
    )

    assert run.calls == []
    assert sleeps == []


def test_clone_repositories_retries_transient_clone_failure_then_succeeds(
    tmp_path: Path,
) -> None:
    url = "https://github.com/acme/private.git"
    failure = subprocess.CalledProcessError(
        128,
        ["git", "clone", url],
        stderr="fatal: could not read Username for 'https://github.com'",
    )
    run = ScriptedRun((failure, None))
    sleeps: list[float] = []

    clone_repositories(
        {"repo_urls": [url]},
        tmp_path,
        run=run,
        sleep=sleeps.append,
    )

    assert len(run.calls) == 2
    assert run.calls[0].command == run.calls[1].command
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_exhausted_clone_retries_raise_sanitized_actionable_error(
    tmp_path: Path,
) -> None:
    credential = "github_pat_secret-value"
    url = f"https://x-access-token:{credential}@github.com/acme/private.git"
    attempted_commands: list[tuple[str, ...]] = []
    sleeps: list[float] = []

    def always_fail(
        command: Sequence[str], **_: Any
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        attempted_commands.append(normalized)
        raise subprocess.CalledProcessError(
            128,
            normalized,
            stderr=f"fatal: unable to access '{url}': credentials unavailable",
        )

    with pytest.raises(HookError) as caught:
        clone_repositories(
            {"repo_urls": [url]},
            tmp_path,
            run=always_fail,
            sleep=sleeps.append,
        )

    message = str(caught.value)
    assert len(attempted_commands) > 1
    assert len(sleeps) == len(attempted_commands) - 1
    assert all(delay > 0 for delay in sleeps)
    assert "clone" in message.lower()
    assert "credential" in message.lower()
    assert credential not in message
    assert url not in message


def test_main_reads_stdin_payload_and_workspace_environment_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "hook_event_name": "sessionStart",
        "repo_urls": ["https://github.com/acme/payments"],
        "repos": [
            {
                "repo_url": "https://github.com/acme/payments",
                "ref": "main",
                "primary": True,
            }
        ],
    }
    captured: dict[str, Any] = {}

    def fake_clone_repositories(
        received_payload: object,
        workspace: Path,
        *,
        run: Callable[..., object],
        sleep: Callable[[float], object],
    ) -> None:
        captured.update(
            payload=received_payload,
            workspace=workspace,
            run=run,
            sleep=sleep,
        )

    def unexpected_prompt(*_: object, **__: object) -> str:
        raise AssertionError("the session-start hook must not prompt")

    monkeypatch.setattr(
        clone_repos_module,
        "clone_repositories",
        fake_clone_repositories,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setenv("CURSOR_WORKER_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", unexpected_prompt)

    assert main([]) == 0
    assert captured["payload"] == payload
    assert captured["workspace"] == tmp_path
    assert callable(captured["run"])
    assert callable(captured["sleep"])


def test_main_reports_malformed_stdin_without_prompt_or_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_prompt(*_: object, **__: object) -> str:
        raise AssertionError("the session-start hook must not prompt")

    monkeypatch.setattr(sys, "stdin", io.StringIO("{not valid JSON"))
    monkeypatch.setattr("builtins.input", unexpected_prompt)

    assert main([]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "error: stdin must contain one valid Cursor sessionStart JSON payload"
    ]
    assert "Traceback" not in captured.err
