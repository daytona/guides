"""Provision, capture, and verify the pinned Cursor Linux VM snapshot."""

from __future__ import annotations

import hashlib
import importlib.resources as resources
import shlex
from collections.abc import Iterator
from importlib.resources.abc import Traversable
from typing import Any

from daytona import CreateSandboxFromSnapshotParams, SandboxClass

from .build_snapshot import SnapshotCollisionError

_LINUX_VM_PROVISIONER = resources.files("cursor_byom").joinpath(
    "provision_linux_vm.sh"
)
_CLONE_HOOK = resources.files("cursor_byom").joinpath("clone_repos.py")
_PROVISIONER_REMOTE_PATH = "/tmp/provision_linux_vm.sh"
_CLONE_HOOK_REMOTE_PATH = "/tmp/clone_repos.py"
_SNAPSHOT_PAGE_LIMIT = 100

LINUX_VM_SNAPSHOT_INPUTS: tuple[Traversable, ...] = (
    _LINUX_VM_PROVISIONER,
    _CLONE_HOOK,
)
LINUX_VM_SNAPSHOT_UPLOADS: tuple[tuple[Traversable, str], ...] = (
    (_LINUX_VM_PROVISIONER, _PROVISIONER_REMOTE_PATH),
    (_CLONE_HOOK, _CLONE_HOOK_REMOTE_PATH),
)


def linux_vm_snapshot_name_for(
    inputs: tuple[Traversable, ...],
    *,
    source_snapshot: str,
    override: str | None = None,
) -> str:
    """Return an explicit name or one derived from the complete VM recipe."""

    explicit_name = (override or "").strip()
    if explicit_name:
        return explicit_name

    digest = hashlib.sha256()
    for snapshot_input in inputs:
        digest.update(snapshot_input.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(snapshot_input.read_bytes())
        digest.update(b"\0")
    digest.update(source_snapshot.encode("utf-8"))
    return f"cursor-byom-linux-vm-{digest.hexdigest()[:8]}"


def _iter_snapshots(daytona: Any) -> Iterator[object]:
    page = 1
    while True:
        result = daytona.snapshot.list(page=page, limit=_SNAPSHOT_PAGE_LIMIT)
        snapshots = getattr(result, "items", None) or []
        yield from snapshots

        total_pages = getattr(result, "total_pages", None)
        if total_pages is not None:
            if page >= int(total_pages):
                return
        elif len(snapshots) < _SNAPSHOT_PAGE_LIMIT:
            return
        page += 1


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _validate_linux_vm_snapshot(snapshot: object, expected_name: str) -> None:
    actual_name = getattr(snapshot, "name", None)
    if actual_name != expected_name:
        raise RuntimeError(
            f"Captured snapshot name is {actual_name!r}; expected {expected_name!r}"
        )

    actual_class = _enum_value(getattr(snapshot, "sandbox_class", None))
    if actual_class != SandboxClass.LINUX_VM.value:
        raise RuntimeError(
            f"Snapshot {expected_name!r} has sandbox_class={actual_class!r}; "
            f"expected {SandboxClass.LINUX_VM.value!r}"
        )

    actual_state = _enum_value(getattr(snapshot, "state", None))
    if actual_state != "active":
        raise RuntimeError(
            f"Snapshot {expected_name!r} has state={actual_state!r}; expected 'active'"
        )


def _find_reusable_snapshot(daytona: Any, name: str) -> object | None:
    for snapshot in _iter_snapshots(daytona):
        if getattr(snapshot, "name", None) != name:
            continue

        actual_class = _enum_value(getattr(snapshot, "sandbox_class", None))
        if actual_class != SandboxClass.LINUX_VM.value:
            raise SnapshotCollisionError(
                f"Snapshot name collision: {name} sandbox_class={actual_class}; "
                f"expected {SandboxClass.LINUX_VM.value}"
            )

        actual_state = _enum_value(getattr(snapshot, "state", None))
        if actual_state == "active":
            return snapshot
        raise SnapshotCollisionError(
            f"Snapshot name collision: {name} state={actual_state}; expected active"
        )
    return None


def _sandbox_name_for(name: str, source_snapshot: str, role: str) -> str:
    digest = hashlib.sha256()
    for value in (name, source_snapshot, role):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return f"cursor-byom-linux-vm-{role}-{digest.hexdigest()[:12]}"


def _sandbox_params(name: str, snapshot: str) -> CreateSandboxFromSnapshotParams:
    return CreateSandboxFromSnapshotParams(
        name=name,
        snapshot=snapshot,
        os_user="daytona",
        env_vars={},
        secrets={},
    )


def _upload_recipe(sandbox: Any, *, timeout: int) -> None:
    for source, destination in LINUX_VM_SNAPSHOT_UPLOADS:
        sandbox.fs.upload_file(source.read_bytes(), destination, timeout=timeout)


def run_linux_vm_provisioner(
    sandbox: Any,
    *,
    verify_only: bool,
    timeout: int,
) -> object:
    """Run the uploaded provisioner and reject every nonzero result."""

    command = f"/bin/bash {shlex.quote(_PROVISIONER_REMOTE_PATH)}"
    if verify_only:
        command = f"{command} VerifyOnly"
    response = sandbox.process.exec(
        command,
        cwd="/home/daytona",
        timeout=timeout,
    )
    exit_code = getattr(response, "exit_code", None)
    if exit_code != 0:
        mode = "verification" if verify_only else "provisioning"
        output = str(getattr(response, "result", "") or "").strip()
        detail = f": {output}" if output else ""
        raise RuntimeError(
            f"Linux VM snapshot {mode} failed with exit code {exit_code}{detail}"
        )
    return response


def _delete_sandbox(
    daytona: Any,
    sandbox: Any,
    *,
    timeout: int,
    primary_error: BaseException | None,
) -> None:
    try:
        daytona.delete(sandbox, timeout=timeout)
    except BaseException as cleanup_error:
        sandbox_name = getattr(sandbox, "name", "unknown")
        message = (
            f"Cleanup also failed for temporary sandbox {sandbox_name!r}: "
            f"{cleanup_error}"
        )
        if primary_error is not None:
            primary_error.add_note(message)
            return
        raise RuntimeError(message) from cleanup_error


def _capture_snapshot(
    daytona: Any,
    *,
    name: str,
    source_snapshot: str,
    build_timeout: int,
    sandbox_timeout: int,
) -> object:
    builder = daytona.create(
        _sandbox_params(
            _sandbox_name_for(name, source_snapshot, "builder"),
            source_snapshot,
        ),
        timeout=sandbox_timeout,
    )
    try:
        _upload_recipe(builder, timeout=sandbox_timeout)
        run_linux_vm_provisioner(
            builder,
            verify_only=False,
            timeout=build_timeout,
        )
        builder.stop(timeout=sandbox_timeout)
        builder._experimental_create_snapshot(name, timeout=build_timeout)
        snapshot = daytona.snapshot.get(name)
        _validate_linux_vm_snapshot(snapshot, name)
    except BaseException as primary_error:
        _delete_sandbox(
            daytona,
            builder,
            timeout=sandbox_timeout,
            primary_error=primary_error,
        )
        raise
    else:
        _delete_sandbox(
            daytona,
            builder,
            timeout=sandbox_timeout,
            primary_error=None,
        )
    return snapshot


def _verify_snapshot(
    daytona: Any,
    snapshot: object,
    *,
    source_snapshot: str,
    sandbox_timeout: int,
) -> None:
    name = str(getattr(snapshot, "name"))
    verifier = daytona.create(
        _sandbox_params(
            _sandbox_name_for(name, source_snapshot, "verifier"),
            name,
        ),
        timeout=sandbox_timeout,
    )
    try:
        _upload_recipe(verifier, timeout=sandbox_timeout)
        run_linux_vm_provisioner(
            verifier,
            verify_only=True,
            timeout=sandbox_timeout,
        )
    except BaseException as primary_error:
        _delete_sandbox(
            daytona,
            verifier,
            timeout=sandbox_timeout,
            primary_error=primary_error,
        )
        raise
    else:
        _delete_sandbox(
            daytona,
            verifier,
            timeout=sandbox_timeout,
            primary_error=None,
        )


def build_linux_vm_snapshot(
    daytona: Any,
    *,
    name: str,
    source_snapshot: str,
    build_timeout: int,
    sandbox_timeout: int,
) -> tuple[object, bool]:
    """Reuse an active Linux VM snapshot or provision and verify a new one."""

    reusable = _find_reusable_snapshot(daytona, name)
    if reusable is not None:
        return reusable, True

    snapshot = _capture_snapshot(
        daytona,
        name=name,
        source_snapshot=source_snapshot,
        build_timeout=build_timeout,
        sandbox_timeout=sandbox_timeout,
    )
    _verify_snapshot(
        daytona,
        snapshot,
        source_snapshot=source_snapshot,
        sandbox_timeout=sandbox_timeout,
    )
    return snapshot, False
