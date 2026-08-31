from __future__ import annotations

import hashlib
import importlib
import pytest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class FakeState:
    value: str


@dataclass(frozen=True)
class FakeSnapshot:
    name: str
    state: FakeState
    sandbox_class: object


class FakeSnapshotClient:
    def __init__(self, existing: list[FakeSnapshot]) -> None:
        self.existing = existing
        self.created: FakeSnapshot | None = None
        self.deleted_snapshots: list[FakeSnapshot] = []
        self.list_calls: list[tuple[int, int]] = []
        self.get_calls: list[str] = []

    def list(self, *, page: int, limit: int) -> object:
        self.list_calls.append((page, limit))
        return SimpleNamespace(items=self.existing, total_pages=1)

    def get(self, name: str) -> FakeSnapshot:
        self.get_calls.append(name)
        if self.created is None or self.created.name != name:
            raise AssertionError(f"snapshot {name!r} was not captured")
        return self.created

    def delete(self, snapshot: FakeSnapshot) -> None:
        self.deleted_snapshots.append(snapshot)


class FakeFs:
    def __init__(self) -> None:
        self.uploads: list[tuple[object, str, int | None]] = []

    def upload_file(
        self,
        source: object,
        destination: str,
        timeout: int | None = None,
    ) -> None:
        self.uploads.append((source, destination, timeout))


class FakeSandbox:
    def __init__(self, name: str, snapshots: FakeSnapshotClient) -> None:
        self.id = f"id-{name}"
        self.name = name
        self.fs = FakeFs()
        self.stop_calls: list[int] = []
        self.snapshot_calls: list[tuple[str, int]] = []
        self._snapshots = snapshots

    def stop(self, *, timeout: int) -> None:
        self.stop_calls.append(timeout)

    def _experimental_create_snapshot(self, name: str, *, timeout: int) -> None:
        self.snapshot_calls.append((name, timeout))
        self._snapshots.created = FakeSnapshot(
            name=name,
            state=FakeState("active"),
            sandbox_class=SimpleNamespace(value="windows"),
        )


class FakeDaytona:
    def __init__(self, existing: list[FakeSnapshot] | None = None) -> None:
        self.snapshot = FakeSnapshotClient(existing or [])
        self.create_calls: list[tuple[object, int]] = []
        self.created: list[FakeSandbox] = []
        self.deleted: list[tuple[FakeSandbox, int]] = []

    def create(self, params: object, *, timeout: int) -> FakeSandbox:
        self.create_calls.append((params, timeout))
        sandbox = FakeSandbox(str(getattr(params, "name")), self.snapshot)
        self.created.append(sandbox)
        return sandbox

    def delete(self, sandbox: FakeSandbox, *, timeout: int) -> None:
        self.deleted.append((sandbox, timeout))


def test_windows_snapshot_name_covers_recipe_and_source_snapshot(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("cursor_byom.build_windows_snapshot")
    provisioner = tmp_path / "provision_windows.ps1"
    clone_hook = tmp_path / "clone_repos_windows.ps1"
    provisioner.write_bytes(b"install cursor\n")
    clone_hook.write_bytes(b"clone repo\n")
    inputs = (provisioner, clone_hook)

    name = module.windows_snapshot_name_for(
        inputs,
        source_snapshot="windows-medium",
    )

    digest = hashlib.sha256()
    for item in inputs:
        digest.update(item.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    digest.update(b"windows-medium")
    assert name == f"cursor-byom-windows-{digest.hexdigest()[:8]}"


def test_windows_snapshot_build_provisions_captures_verifies_and_cleans_up(
    monkeypatch: Any,
) -> None:
    module = importlib.import_module("cursor_byom.build_windows_snapshot")
    daytona = FakeDaytona()
    provision_calls: list[tuple[FakeSandbox, bool, int]] = []

    def run_provisioner(
        sandbox: FakeSandbox,
        *,
        verify_only: bool,
        timeout: int,
    ) -> object:
        provision_calls.append((sandbox, verify_only, timeout))
        return SimpleNamespace(exit_code=0, result="verified")

    monkeypatch.setattr(module, "run_windows_provisioner", run_provisioner)

    snapshot, reused = module.build_windows_snapshot(
        daytona,
        name="cursor-byom-windows-test",
        source_snapshot="windows-medium",
        build_timeout=1800,
        sandbox_timeout=300,
    )

    assert reused is False
    assert snapshot.name == "cursor-byom-windows-test"
    assert len(daytona.created) == 2
    builder, verifier = daytona.created
    assert getattr(daytona.create_calls[0][0], "snapshot") == "windows-medium"
    assert getattr(daytona.create_calls[1][0], "snapshot") == snapshot.name
    assert builder.stop_calls == [300]
    assert builder.snapshot_calls == [(snapshot.name, 1800)]
    assert provision_calls == [
        (builder, False, 1800),
        (verifier, True, 300),
    ]
    assert daytona.deleted == [(builder, 300), (verifier, 300)]
    expected_destinations = {
        remote for _, remote in module.WINDOWS_SNAPSHOT_UPLOADS
    }
    assert {destination for _, destination, _ in builder.fs.uploads} == (
        expected_destinations
    )
    assert {destination for _, destination, _ in verifier.fs.uploads} == (
        expected_destinations
    )
    assert all(isinstance(source, bytes) for source, _, _ in builder.fs.uploads)
    assert all(isinstance(source, bytes) for source, _, _ in verifier.fs.uploads)


def test_active_windows_snapshot_is_reused_without_sandbox_creation() -> None:
    module = importlib.import_module("cursor_byom.build_windows_snapshot")
    existing = FakeSnapshot(
        name="cursor-byom-windows-test",
        state=FakeState("active"),
        sandbox_class=SimpleNamespace(value="windows"),
    )
    daytona = FakeDaytona([existing])

    snapshot, reused = module.build_windows_snapshot(
        daytona,
        name=existing.name,
        source_snapshot="windows-medium",
        build_timeout=1800,
        sandbox_timeout=300,
    )

    assert snapshot is existing
    assert reused is True
    assert daytona.created == []
    assert daytona.deleted == []


def test_windows_provisioner_command_uses_unquoted_daytona_executable() -> None:
    module = importlib.import_module("cursor_byom.build_windows_snapshot")

    command = module._powershell_encoded("Write-Output 'ready'")

    assert command.startswith(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe "
    )


def test_windows_provisioner_pins_node_22_and_probes_native_module() -> None:
    provisioner = (
        Path(__file__).parents[1]
        / "cursor_byom"
        / "provision_windows.ps1"
    ).read_text()

    assert "$NodeVersion = '22.23.2'" in provisioner
    assert (
        "$NodeExecutableSha256 = "
        "'0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4'"
        in provisioner
    )
    assert "require(process.argv[1])" in provisioner
    assert "node_modules\\better-sqlite3" in provisioner


def test_failed_windows_verification_deletes_uncertified_snapshot(
    monkeypatch: Any,
) -> None:
    module = importlib.import_module("cursor_byom.build_windows_snapshot")
    daytona = FakeDaytona()

    def run_provisioner(
        sandbox: FakeSandbox,
        *,
        verify_only: bool,
        timeout: int,
    ) -> object:
        if verify_only:
            raise RuntimeError("verification transport failed")
        return SimpleNamespace(exit_code=0, result="provisioned")

    monkeypatch.setattr(module, "run_windows_provisioner", run_provisioner)

    with pytest.raises(RuntimeError, match="verification transport failed"):
        module.build_windows_snapshot(
            daytona,
            name="cursor-byom-windows-unverified",
            source_snapshot="windows-medium",
            build_timeout=1800,
            sandbox_timeout=300,
        )

    assert daytona.snapshot.deleted_snapshots == [daytona.snapshot.created]
