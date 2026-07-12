"""Build the Linux snapshot with the Devin CLI and desktop dependencies baked in.

The default snapshot name is derived from the packaged Dockerfile recipe hash.
"""

from __future__ import annotations

import hashlib
import logging
import importlib.resources as resources
import os
import sys
from pathlib import Path
from typing import Iterator

from daytona import CreateSnapshotParams, Daytona, Image, Resources
from daytona_api_client import SnapshotState
from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

DOCKERFILE = resources.files("devin_outposts").joinpath("Dockerfile.default")
DEFAULT_SNAPSHOT_PREFIX = "devin-outposts-default"
DEFAULT_CPU = 2
DEFAULT_MEMORY_GB = 8
DEFAULT_DISK_GB = 10
SNAPSHOT_PAGE_LIMIT = 100
EXIT_COLLISION = 4


def load_env_file(path: Path = Path(".env")) -> None:
    """Load `.env` when present. Existing process env values take precedence."""
    load_dotenv(path, override=False)


def dockerfile_sha8(path: Path = DOCKERFILE) -> str:
    """Make snapshot names deterministic for the exact Dockerfile contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def snapshot_name(sha8: str) -> str:
    """Use an explicit name when provided, otherwise derive one from the image recipe."""
    override = os.environ.get("SNAPSHOT_NAME", "").strip()
    return override or f"{DEFAULT_SNAPSHOT_PREFIX}-{sha8}"


def iter_snapshots(daytona: Daytona) -> Iterator[object]:
    """Page through snapshots so an existing hash-derived snapshot can be reused."""
    page = 1
    while True:
        result = daytona.snapshot.list(page=page, limit=SNAPSHOT_PAGE_LIMIT)
        items = getattr(result, "items", []) or []
        yield from items

        total_pages = getattr(result, "total_pages", None)
        if total_pages is not None:
            if page >= total_pages:
                return
        elif len(items) < SNAPSHOT_PAGE_LIMIT:
            return
        page += 1


def find_snapshot(daytona: Daytona, name: str) -> object | None:
    """Return an existing snapshot with this name, if Daytona already has it."""
    for snapshot in iter_snapshots(daytona):
        if getattr(snapshot, "name", None) == name:
            return snapshot
    return None


def stream_log(chunk: str) -> None:
    """Forward Daytona build logs without buffering the whole image build."""
    if not chunk:
        return
    sys.stdout.write(chunk)
    if not chunk.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    load_env_file()

    sha8 = dockerfile_sha8()
    name = snapshot_name(sha8)
    print(f"Dockerfile SHA-256 prefix: {sha8}")
    print(f"Snapshot name: {name}")

    daytona = Daytona()
    existing = find_snapshot(daytona, name)
    if existing is not None:
        state = getattr(existing, "state", None)
        state_value = getattr(state, "value", state or "unknown")
        if state != SnapshotState.ACTIVE:
            print(
                f"Snapshot name collision: {name} state={state_value}; expected active",
                file=sys.stderr,
            )
            return EXIT_COLLISION
        print(f"Reusing snapshot: {name} state={state_value}")
        return 0

    with resources.as_file(DOCKERFILE) as dockerfile_path:
        params = CreateSnapshotParams(
            name=name,
            image=Image.from_dockerfile(dockerfile_path),
            resources=Resources(
                cpu=DEFAULT_CPU,
                memory=DEFAULT_MEMORY_GB,
                disk=DEFAULT_DISK_GB,
            ),
        )

        snapshot = daytona.snapshot.create(params, on_logs=stream_log, timeout=0)
    state = getattr(snapshot, "state", "unknown")
    print(f"Snapshot ready: {getattr(snapshot, 'name', name)} state={state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
