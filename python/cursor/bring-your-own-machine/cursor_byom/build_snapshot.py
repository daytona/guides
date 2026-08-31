"""Build or reuse the pinned Cursor worker snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.resources as resources
import json
import os
import sys
from collections.abc import Iterator
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from daytona import CreateSnapshotParams, Daytona, Image, Resources
from dotenv import load_dotenv

DOCKERFILE = resources.files("cursor_byom").joinpath("Dockerfile")
CLONE_HOOK = resources.files("cursor_byom").joinpath("clone_repos.py")
SNAPSHOT_INPUTS = (DOCKERFILE, CLONE_HOOK)
DEFAULT_SNAPSHOT_PREFIX = "cursor-byom-default"
DEFAULT_CPU = 2
DEFAULT_MEMORY_GB = 8
DEFAULT_DISK_GB = 10
SNAPSHOT_PAGE_LIMIT = 100
EXIT_ERROR = 1
EXIT_COLLISION = 4


class SnapshotCollisionError(RuntimeError):
    """A snapshot has the requested name but cannot be reused."""


def snapshot_name_for(
    inputs: tuple[Traversable, ...],
    override: str | None = None,
) -> str:
    """Return an explicit name or one derived from the exact image inputs."""
    explicit_name = (override or "").strip()
    if explicit_name:
        return explicit_name

    digest = hashlib.sha256()
    for snapshot_input in inputs:
        digest.update(snapshot_input.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(snapshot_input.read_bytes())
        digest.update(b"\0")
    return f"{DEFAULT_SNAPSHOT_PREFIX}-{digest.hexdigest()[:8]}"


def _iter_snapshots(daytona: Any) -> Iterator[object]:
    page = 1
    while True:
        result = daytona.snapshot.list(page=page, limit=SNAPSHOT_PAGE_LIMIT)
        snapshots = getattr(result, "items", []) or []
        yield from snapshots

        total_pages = getattr(result, "total_pages", None)
        if total_pages is not None:
            if page >= total_pages:
                return
        elif len(snapshots) < SNAPSHOT_PAGE_LIMIT:
            return
        page += 1


def _state_value(snapshot: object) -> str:
    state = getattr(snapshot, "state", None)
    return str(getattr(state, "value", state or "unknown"))


def find_reusable_snapshot(daytona: Any, name: str) -> object | None:
    """Return the matching active snapshot and reject all other matching states."""
    for snapshot in _iter_snapshots(daytona):
        if getattr(snapshot, "name", None) != name:
            continue

        state = _state_value(snapshot)
        if state == "active":
            return snapshot
        raise SnapshotCollisionError(
            f"Snapshot name collision: {name} state={state}; expected active"
        )
    return None


def _stream_build_log(chunk: str) -> None:
    if not chunk:
        return
    sys.stderr.write(chunk)
    if not chunk.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def _write_result(snapshot: object, name: str, *, reused: bool) -> None:
    result = {
        "reused": reused,
        "snapshot_name": getattr(snapshot, "name", name),
        "state": _state_value(snapshot),
    }
    print(json.dumps(result, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    """Build the configured snapshot without prompts."""
    parser = argparse.ArgumentParser(
        prog="build-cursor-byom-snapshot",
        description="Build or reuse the pinned Cursor worker snapshot.",
        epilog="Examples:\n  build-cursor-byom-snapshot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.parse_args(argv)
    load_dotenv(Path(".env"), override=False)
    name: str | None = None

    try:
        name = snapshot_name_for(SNAPSHOT_INPUTS, os.environ.get("SNAPSHOT_NAME"))
        daytona = Daytona()
        existing = find_reusable_snapshot(daytona, name)
        if existing is not None:
            _write_result(existing, name, reused=True)
            return 0

        with resources.as_file(DOCKERFILE) as dockerfile:
            snapshot = daytona.snapshot.create(
                CreateSnapshotParams(
                    name=name,
                    image=Image.from_dockerfile(dockerfile),
                    resources=Resources(
                        cpu=DEFAULT_CPU,
                        memory=DEFAULT_MEMORY_GB,
                        disk=DEFAULT_DISK_GB,
                    ),
                ),
                on_logs=_stream_build_log,
                timeout=0,
            )
        _write_result(snapshot, name, reused=False)
        return 0
    except SnapshotCollisionError as error:
        print(
            f"{error}. Choose another SNAPSHOT_NAME or wait for the snapshot "
            "to become active.",
            file=sys.stderr,
        )
        return EXIT_COLLISION
    except Exception as error:
        target = name or "Cursor snapshot"
        print(f"Failed to build {target}: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
