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

from daytona import (
    CreateSnapshotParams,
    Daytona,
    DaytonaConfig,
    Image,
    Resources,
    SandboxClass,
)
from dotenv import load_dotenv

from .build_linux_vm_snapshot import (
    LINUX_VM_SNAPSHOT_INPUTS,
    LINUX_VM_SOURCE_SNAPSHOT,
    LinuxVmSnapshotCollisionError,
    build_linux_vm_snapshot,
    linux_vm_snapshot_name_for,
)

from .build_windows_snapshot import (
    WINDOWS_SNAPSHOT_INPUTS,
    WINDOWS_SOURCE_SNAPSHOT,
    WindowsSnapshotCollisionError,
    build_windows_snapshot,
    windows_snapshot_name_for,
)

CONTAINER_DOCKERFILE = resources.files("cursor_self_hosted").joinpath("Dockerfile")
DEFAULT_CPU = 2
DEFAULT_MEMORY_GB = 8
DEFAULT_DISK_GB = 10
SNAPSHOT_PAGE_LIMIT = 100
EXIT_ERROR = 1
EXIT_COLLISION = 4


class SnapshotCollisionError(RuntimeError):
    """A snapshot has the requested name but cannot be reused."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed



def snapshot_inputs_for(
    sandbox_class: SandboxClass,
) -> tuple[Traversable, ...]:
    """Return the exact recipe files for a container snapshot."""

    if sandbox_class == SandboxClass.CONTAINER:
        return (CONTAINER_DOCKERFILE,)
    raise ValueError(
        f"{sandbox_class.value} snapshots need a platform-specific builder"
    )

def snapshot_name_for(
    inputs: tuple[Traversable, ...],
    sandbox_class: SandboxClass,
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
    return f"cursor-self-hosted-{sandbox_class.value}-{digest.hexdigest()[:8]}"


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


def find_reusable_snapshot(
    daytona: Any,
    name: str,
    sandbox_class: SandboxClass,
) -> object | None:
    """Return the matching active snapshot and reject all other matches."""
    for snapshot in _iter_snapshots(daytona):
        if getattr(snapshot, "name", None) != name:
            continue

        actual_class = getattr(snapshot, "sandbox_class", None)
        actual_class_value = str(getattr(actual_class, "value", actual_class))
        if actual_class_value != sandbox_class.value:
            raise SnapshotCollisionError(
                f"Snapshot name collision: {name} "
                f"sandbox_class={actual_class_value}; expected {sandbox_class.value}"
            )
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


def _write_result(
    snapshot: object,
    name: str,
    *,
    reused: bool,
    sandbox_class: SandboxClass,
    target: str | None,
) -> None:
    result = {
        "reused": reused,
        "sandbox_class": sandbox_class.value,
        "snapshot_name": getattr(snapshot, "name", name),
        "state": _state_value(snapshot),
        "target": target,
    }
    print(json.dumps(result, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    """Build the configured snapshot without prompts."""
    parser = argparse.ArgumentParser(
        prog="build-cursor-self-hosted-snapshot",
        description="Build or reuse a Cursor worker snapshot.",
        epilog=(
            "Examples:\n"
            "  build-cursor-self-hosted-snapshot\n"
            "  build-cursor-self-hosted-snapshot --sandbox-class container --target us\n"
            "  build-cursor-self-hosted-snapshot --sandbox-class linux-vm "
            "--target eu-central-1\n"
            "  build-cursor-self-hosted-snapshot --sandbox-class windows --target us"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sandbox-class",
        choices=tuple(
            item.value
            for item in (
                SandboxClass.CONTAINER,
                SandboxClass.LINUX_VM,
                SandboxClass.WINDOWS,
            )
        ),
        default=SandboxClass.CONTAINER.value,
        help="Daytona sandbox class to build (default: container)",
    )
    parser.add_argument(
        "--target",
        help="Daytona target region (default: DAYTONA_TARGET or organization default)",
    )
    parser.add_argument(
        "--name",
        help="snapshot name (default: SNAPSHOT_NAME or content-derived name)",
    )
    parser.add_argument(
        "--source-snapshot",
        help="source VM snapshot (used only for linux-vm and windows)",
    )
    parser.add_argument(
        "--build-timeout",
        type=_positive_int,
        default=1800,
        help="seconds allowed for VM provisioning and snapshot capture (default: 1800)",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=_positive_int,
        default=300,
        help="seconds allowed for VM create, verify, and cleanup (default: 300)",
    )
    args = parser.parse_args(argv)
    load_dotenv(Path(".env"), override=False)
    sandbox_class = SandboxClass(args.sandbox_class)
    target = args.target or os.environ.get("DAYTONA_TARGET")
    name_override = args.name or os.environ.get("SNAPSHOT_NAME")
    name: str | None = None

    try:
        daytona = Daytona(DaytonaConfig(target=target))
        if sandbox_class == SandboxClass.LINUX_VM:
            source_snapshot = args.source_snapshot or LINUX_VM_SOURCE_SNAPSHOT
            name = linux_vm_snapshot_name_for(
                LINUX_VM_SNAPSHOT_INPUTS,
                source_snapshot=source_snapshot,
                override=name_override,
            )
            snapshot, reused = build_linux_vm_snapshot(
                daytona,
                name=name,
                source_snapshot=source_snapshot,
                build_timeout=args.build_timeout,
                sandbox_timeout=args.sandbox_timeout,
            )
            _write_result(
                snapshot,
                name,
                reused=reused,
                sandbox_class=sandbox_class,
                target=target,
            )
            return 0

        if sandbox_class == SandboxClass.WINDOWS:
            source_snapshot = args.source_snapshot or WINDOWS_SOURCE_SNAPSHOT
            name = windows_snapshot_name_for(
                WINDOWS_SNAPSHOT_INPUTS,
                source_snapshot=source_snapshot,
                override=name_override,
            )
            snapshot, reused = build_windows_snapshot(
                daytona,
                name=name,
                source_snapshot=source_snapshot,
                build_timeout=args.build_timeout,
                sandbox_timeout=args.sandbox_timeout,
            )
            _write_result(
                snapshot,
                name,
                reused=reused,
                sandbox_class=sandbox_class,
                target=target,
            )
            return 0

        snapshot_inputs = snapshot_inputs_for(sandbox_class)
        name = snapshot_name_for(snapshot_inputs, sandbox_class, name_override)
        existing = find_reusable_snapshot(daytona, name, sandbox_class)
        if existing is not None:
            _write_result(
                existing,
                name,
                reused=True,
                sandbox_class=sandbox_class,
                target=target,
            )
            return 0

        with resources.as_file(snapshot_inputs[0]) as dockerfile:
            snapshot = daytona.snapshot.create(
                CreateSnapshotParams(
                    name=name,
                    image=Image.from_dockerfile(dockerfile),
                    resources=Resources(
                        cpu=DEFAULT_CPU,
                        memory=DEFAULT_MEMORY_GB,
                        disk=DEFAULT_DISK_GB,
                    ),
                    region_id=target,
                    sandbox_class=sandbox_class,
                ),
                on_logs=_stream_build_log,
                timeout=0,
            )
        _write_result(
            snapshot,
            name,
            reused=False,
            sandbox_class=sandbox_class,
            target=target,
        )
        return 0
    except (
        SnapshotCollisionError,
        LinuxVmSnapshotCollisionError,
        WindowsSnapshotCollisionError,
    ) as error:
        print(
            f"{error}. Choose another snapshot name or wait for it to become active.",
            file=sys.stderr,
        )
        return EXIT_COLLISION
    except Exception as error:
        target = name or "Cursor snapshot"
        print(f"Failed to build {target}: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
