from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from cursor_byom import build_snapshot as snapshot_module
from cursor_byom.build_snapshot import (
    SNAPSHOT_INPUTS,
    SnapshotCollisionError,
    find_reusable_snapshot,
    snapshot_name_for,
)


@dataclass(frozen=True)
class FakeSnapshotState:
    value: str


@dataclass(frozen=True)
class FakeSnapshot:
    name: str
    state: FakeSnapshotState


@dataclass(frozen=True)
class FakeSnapshotPage:
    items: list[FakeSnapshot]
    total_pages: int = 1


class FakeSnapshotClient:
    def __init__(self, pages: list[list[FakeSnapshot]]) -> None:
        self._pages = pages
        self.list_calls: list[int] = []

    def list(self, *, page: int, limit: int) -> FakeSnapshotPage:
        self.list_calls.append(page)
        return FakeSnapshotPage(
            items=self._pages[page - 1],
            total_pages=len(self._pages),
        )


class FakeDaytona:
    def __init__(self, pages: list[list[FakeSnapshot]]) -> None:
        self.snapshot = FakeSnapshotClient(pages)


def test_default_snapshot_name_contains_exact_snapshot_inputs_sha256_prefix(
    tmp_path: Path,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    clone_hook = tmp_path / "clone_repos.py"
    dockerfile.write_bytes(b"FROM python:3.13-slim\n")
    clone_hook.write_bytes(b"#!/usr/bin/env python3\nprint('clone')\n")

    name = snapshot_name_for((dockerfile, clone_hook))

    expected_sha8 = hashlib.sha256(
        b"Dockerfile\0"
        b"FROM python:3.13-slim\n\0"
        b"clone_repos.py\0"
        b"#!/usr/bin/env python3\nprint('clone')\n\0"
    ).hexdigest()[:8]
    assert name == f"cursor-byom-default-{expected_sha8}"


def test_default_snapshot_name_changes_when_only_dockerfile_changes(
    tmp_path: Path,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    clone_hook = tmp_path / "clone_repos.py"
    dockerfile.write_bytes(b"FROM python:3.13-slim\n")
    clone_hook.write_bytes(b"#!/usr/bin/env python3\n")
    inputs = (dockerfile, clone_hook)

    original_name = snapshot_name_for(inputs)
    dockerfile.write_bytes(b"FROM python:3.14-slim\n")

    assert snapshot_name_for(inputs) != original_name


def test_default_snapshot_name_changes_when_only_clone_hook_changes(
    tmp_path: Path,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    clone_hook = tmp_path / "clone_repos.py"
    dockerfile.write_bytes(b"FROM python:3.13-slim\n")
    clone_hook.write_bytes(b"#!/usr/bin/env python3\n")
    inputs = (dockerfile, clone_hook)

    original_name = snapshot_name_for(inputs)
    clone_hook.write_bytes(b"#!/usr/bin/env python3\nprint('clone')\n")

    assert snapshot_name_for(inputs) != original_name


def test_explicit_snapshot_name_override_is_trimmed_without_reading_inputs(
    tmp_path: Path,
) -> None:
    missing_inputs = (
        tmp_path / "missing" / "Dockerfile",
        tmp_path / "missing" / "clone_repos.py",
    )

    name = snapshot_name_for(
        missing_inputs,
        override="  operator-snapshot  ",
    )

    assert name == "operator-snapshot"


def test_snapshot_inputs_are_exact_packaged_image_inputs() -> None:
    snapshot_file = snapshot_module.__file__
    assert snapshot_file is not None
    package_dir = Path(snapshot_file).parent

    assert tuple(SNAPSHOT_INPUTS) == (
        package_dir / "Dockerfile",
        package_dir / "clone_repos.py",
    )


def test_active_snapshot_with_matching_name_is_reused() -> None:
    existing = FakeSnapshot(
        name="cursor-byom-default-ba7816bf",
        state=FakeSnapshotState("active"),
    )
    daytona = FakeDaytona([[existing]])

    found = find_reusable_snapshot(daytona, existing.name)

    assert found is existing


def test_active_snapshot_with_matching_name_on_second_page_is_reused() -> None:
    existing = FakeSnapshot(
        name="cursor-byom-default-ba7816bf",
        state=FakeSnapshotState("active"),
    )
    daytona = FakeDaytona(
        [
            [
                FakeSnapshot(
                    name="different-snapshot",
                    state=FakeSnapshotState("active"),
                )
            ],
            [existing],
        ]
    )

    found = find_reusable_snapshot(daytona, existing.name)

    assert found is existing
    assert daytona.snapshot.list_calls == [1, 2]


def test_non_active_snapshot_with_matching_name_raises_collision_error() -> None:
    existing = FakeSnapshot(
        name="cursor-byom-default-ba7816bf",
        state=FakeSnapshotState("building"),
    )
    daytona = FakeDaytona([[existing]])

    with pytest.raises(SnapshotCollisionError) as caught:
        find_reusable_snapshot(daytona, existing.name)

    assert str(caught.value) == (
        "Snapshot name collision: cursor-byom-default-ba7816bf "
        "state=building; expected active"
    )


def test_dockerfile_installs_executable_clone_hook_without_unsupported_flag() -> None:
    snapshot_file = snapshot_module.__file__
    assert snapshot_file is not None
    dockerfile = (
        Path(snapshot_file).with_name("Dockerfile").read_text()
    )
    hook_path = "/usr/local/bin/clone-cursor-byom-repos"
    copy_line = next(
        (
            line
            for line in dockerfile.splitlines()
            if line.startswith("COPY ")
            and "clone_repos.py" in line
            and hook_path in line
        ),
        None,
    )

    assert copy_line is not None
    copy_makes_executable = (
        re.search(r"--chmod=0?755(?:\s|$)", copy_line) is not None
    )
    later_chmod_makes_executable = (
        re.search(
            (
                rf"(?m)^\s*(?:RUN\s+)?chmod\s+(?:0?755|\+x)\s+"
                rf"{re.escape(hook_path)}(?:\s|$)"
            ),
            dockerfile,
        )
        is not None
    )
    assert copy_makes_executable or later_chmod_makes_executable
    assert "--clone-git-repos" not in dockerfile


def test_clone_hook_source_starts_with_python3_shebang() -> None:
    snapshot_file = snapshot_module.__file__
    assert snapshot_file is not None
    clone_hook = Path(snapshot_file).with_name("clone_repos.py")

    assert clone_hook.read_bytes().startswith(b"#!/usr/bin/env python3\n")
