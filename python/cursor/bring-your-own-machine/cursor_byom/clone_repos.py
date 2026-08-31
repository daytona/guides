#!/usr/bin/env python3
"""Prepare repositories for a claimed Cursor worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


CLONE_ATTEMPTS = 5
RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)


class HookError(RuntimeError):
    """The session-start repository setup failed."""


@dataclass(frozen=True)
class Repo:
    url: str
    ref: str | None = None


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookError(f"{field} must be a non-empty string")
    return value


def repos_from_payload(payload: object) -> tuple[Repo, ...]:
    """Validate repository metadata from a Cursor session-start payload."""
    if not isinstance(payload, dict):
        raise HookError("payload must be a JSON object")

    if "repos" in payload:
        raw_repos = payload["repos"]
        if not isinstance(raw_repos, list):
            raise HookError("repos must be a JSON array")

        repos: list[Repo] = []
        for index, raw_repo in enumerate(raw_repos):
            if not isinstance(raw_repo, dict):
                raise HookError(f"repos[{index}] must be a JSON object")

            url = _required_string(
                raw_repo.get("repo_url"),
                f"repos[{index}].repo_url",
            )
            raw_ref = raw_repo.get("ref")
            ref = (
                None
                if raw_ref is None
                else _required_string(raw_ref, f"repos[{index}].ref")
            )
            repos.append(Repo(url=url, ref=ref))
        return tuple(repos)

    raw_urls = payload.get("repo_urls", [])
    if not isinstance(raw_urls, list):
        raise HookError("repo_urls must be a JSON array")

    return tuple(
        Repo(
            url=_required_string(raw_url, f"repo_urls[{index}]"),
        )
        for index, raw_url in enumerate(raw_urls)
    )


def target_name(url: str, used_names: set[str] | None = None) -> str:
    """Return a safe, stable, URL-specific directory name."""
    url = _required_string(url, "repo_url")
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = urlsplit("")
        path = url
    else:
        path = parsed.path
    if not parsed.scheme and ":" in path:
        path = path.rsplit(":", 1)[-1]

    basename = unquote(path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1])
    if basename.lower().endswith(".git"):
        basename = basename[:-4]
    basename = re.sub(r"[^A-Za-z0-9._-]+", "-", basename)
    while ".." in basename:
        basename = basename.replace("..", ".")
    basename = basename.strip("._-")
    if not basename or not basename[0].isalnum():
        basename = "repo"

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    stem = f"{basename}-{digest}"
    candidate = stem

    if used_names is not None:
        suffix = 2
        while candidate in used_names:
            candidate = f"{stem}-{suffix}"
            suffix += 1
        used_names.add(candidate)

    return candidate


def _remove_partial_clone(destination: Path) -> None:
    try:
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.exists():
            shutil.rmtree(destination)
    except OSError:
        raise HookError(
            "Could not remove a partial repository clone; "
            "check workspace permissions and retry."
        ) from None


def _run_git(
    command: Sequence[str],
    *,
    run: Callable[..., object],
) -> None:
    run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def clone_repositories(
    payload: object,
    workspace: Path,
    *,
    run: Callable[..., object],
    sleep: Callable[[float], object],
) -> tuple[Path, ...]:
    """Clone all repositories requested by a validated hook payload."""
    repos = repos_from_payload(payload)
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HookError(
            "Could not prepare the Cursor workspace; "
            "check CURSOR_WORKER_WORKSPACE_DIR permissions."
        ) from None

    used_names: set[str] = set()
    names_by_url: dict[str, str] = {}
    destinations: list[Path] = []
    for repo in repos:
        name = names_by_url.get(repo.url)
        if name is None:
            name = target_name(repo.url, used_names)
            names_by_url[repo.url] = name
        destination = workspace / name
        destinations.append(destination)

        if not destination.is_symlink() and (destination / ".git").is_dir():
            continue

        _remove_partial_clone(destination)
        for attempt in range(CLONE_ATTEMPTS):
            try:
                _run_git(
                    ("git", "clone", "--", repo.url, str(destination)),
                    run=run,
                )
                break
            except subprocess.CalledProcessError:
                _remove_partial_clone(destination)
                if attempt == CLONE_ATTEMPTS - 1:
                    raise HookError(
                        "Repository clone failed after credential retries; "
                        "verify that the minted GitHub credential can access "
                        "every configured repository."
                    ) from None
                sleep(RETRY_DELAYS[attempt])
            except OSError:
                _remove_partial_clone(destination)
                raise HookError(
                    "Could not start git clone; verify that git is installed "
                    "and the workspace is writable."
                ) from None

        if repo.ref is not None:
            try:
                _run_git(
                    (
                        "git",
                        "-C",
                        str(destination),
                        "checkout",
                        "--detach",
                        repo.ref,
                    ),
                    run=run,
                )
            except (OSError, subprocess.CalledProcessError):
                _remove_partial_clone(destination)
                raise HookError(
                    "Repository checkout failed; verify that each configured "
                    "ref exists and is accessible."
                ) from None

    return tuple(destinations)


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Clone repositories from one Cursor sessionStart JSON payload "
            "read from standard input."
        ),
        epilog=(
            "Example: cursor-hook < session-start.json\n"
            "The destination is read from CURSOR_WORKER_WORKSPACE_DIR."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)

    try:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, UnicodeError):
            raise HookError(
                "stdin must contain one valid Cursor sessionStart JSON payload"
            ) from None

        workspace_value = os.environ.get("CURSOR_WORKER_WORKSPACE_DIR")
        if workspace_value is None or not workspace_value.strip():
            raise HookError(
                "CURSOR_WORKER_WORKSPACE_DIR must name the worker workspace"
            )

        clone_repositories(
            payload,
            Path(workspace_value),
            run=subprocess.run,
            sleep=time.sleep,
        )
    except HookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps({"status": "ok"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
