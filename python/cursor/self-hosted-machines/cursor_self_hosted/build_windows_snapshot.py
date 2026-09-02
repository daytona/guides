"""Build or reuse the pinned Cursor Windows worker snapshot."""

from __future__ import annotations

import base64
import hashlib
import importlib.resources as resources
import time
import uuid
from collections.abc import Iterator
from importlib.resources.abc import Traversable
from typing import Any

from daytona import (
    CreateSandboxFromSnapshotParams,
    DaytonaError,
    ExecuteResponse,
    SandboxClass,
)

WINDOWS_PROVISIONER = resources.files("cursor_self_hosted").joinpath("provision_windows.ps1")
WINDOWS_CHECKOUT_HOOK = resources.files("cursor_self_hosted").joinpath("checkout_repo.ps1")
WINDOWS_CHECKOUT_WRAPPER = resources.files("cursor_self_hosted").joinpath("checkout_repo.cmd")
WINDOWS_BOOTSTRAP = resources.files("cursor_self_hosted").joinpath("windows_bootstrap.ps1")

WINDOWS_SNAPSHOT_INPUTS = (
    WINDOWS_PROVISIONER,
    WINDOWS_CHECKOUT_HOOK,
    WINDOWS_CHECKOUT_WRAPPER,
    WINDOWS_BOOTSTRAP,
)
WINDOWS_SNAPSHOT_UPLOADS = (
    (WINDOWS_PROVISIONER, "C:/Windows/Temp/provision_windows.ps1"),
    (WINDOWS_CHECKOUT_HOOK, "C:/Windows/Temp/checkout_repo.ps1"),
    (WINDOWS_CHECKOUT_WRAPPER, "C:/Windows/Temp/checkout_repo.cmd"),
    (WINDOWS_BOOTSTRAP, "C:/Windows/Temp/windows_bootstrap.ps1"),
)

WINDOWS_SOURCE_SNAPSHOT = "windows-medium"
WINDOWS_SANDBOX_CLASS = SandboxClass.WINDOWS.value
WINDOWS_SNAPSHOT_PAGE_LIMIT = 100
WINDOWS_PROVISION_POLL_SECONDS = 5
WINDOWS_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
WINDOWS_REMOTE_PROVISIONER = r"C:\Windows\Temp\provision_windows.ps1"


class WindowsSnapshotCollisionError(RuntimeError):
    """A snapshot has the requested name but cannot be reused."""


class WindowsSnapshotCleanupError(RuntimeError):
    """A temporary Windows sandbox could not be deleted."""


def windows_snapshot_name_for(
    inputs: tuple[Traversable, ...],
    *,
    source_snapshot: str,
    override: str | None = None,
) -> str:
    """Return an explicit name or one derived from every exact recipe input."""
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
    return f"cursor-self-hosted-windows-{digest.hexdigest()[:8]}"


def _iter_snapshots(daytona: Any) -> Iterator[object]:
    page = 1
    while True:
        result = daytona.snapshot.list(page=page, limit=WINDOWS_SNAPSHOT_PAGE_LIMIT)
        snapshots = getattr(result, "items", []) or []
        yield from snapshots

        total_pages = getattr(result, "total_pages", None)
        if total_pages is not None:
            if page >= total_pages:
                return
        elif len(snapshots) < WINDOWS_SNAPSHOT_PAGE_LIMIT:
            return
        page += 1


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _validate_windows_snapshot(snapshot: object, name: str) -> None:
    actual_class = _enum_value(getattr(snapshot, "sandbox_class", None))
    if actual_class != WINDOWS_SANDBOX_CLASS:
        raise WindowsSnapshotCollisionError(
            f"Snapshot name collision: {name} sandbox_class={actual_class}; "
            f"expected {WINDOWS_SANDBOX_CLASS}"
        )

    state = _enum_value(getattr(snapshot, "state", None))
    if state != "active":
        raise WindowsSnapshotCollisionError(
            f"Snapshot name collision: {name} state={state}; expected active"
        )


def _find_reusable_snapshot(daytona: Any, name: str) -> object | None:
    for snapshot in _iter_snapshots(daytona):
        if getattr(snapshot, "name", None) != name:
            continue
        _validate_windows_snapshot(snapshot, name)
        return snapshot
    return None


def _powershell_encoded(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return (
        f"{WINDOWS_POWERSHELL} -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -EncodedCommand {encoded}"
    )


def _is_not_found(error: BaseException) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    for status_code in (
        getattr(error, "status_code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        if status_code is None:
            continue
        try:
            if int(status_code) == 404:
                return True
        except (TypeError, ValueError):
            pass
    return error.__class__.__name__ in {"NotFoundError", "NotFoundException"}


def _download_text(sandbox: Any, path: str, *, encoding: str) -> str:
    content = sandbox.fs.download_file(path)
    if isinstance(content, bytes):
        if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return content.decode("utf-16", errors="replace")
        return content.decode(encoding, errors="replace")
    return str(content or "")


def run_windows_provisioner(
    sandbox: Any,
    *,
    verify_only: bool,
    timeout: int,
) -> ExecuteResponse:
    """Run the provisioner detached and poll its log and exit marker."""
    run_id = uuid.uuid4().hex
    log_path = f"C:/Windows/Temp/cursor-self-hosted-provision-{run_id}.log"
    exit_path = f"C:/Windows/Temp/cursor-self-hosted-provision-{run_id}.exitcode"

    provision_arguments = (
        f"& '{WINDOWS_POWERSHELL}' -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -File '{WINDOWS_REMOTE_PROVISIONER}'"
    )
    if verify_only:
        provision_arguments += " -VerifyOnly"
    worker_script = (
        f"{provision_arguments} *> '{log_path}'\r\n"
        "$provisionExitCode = $LASTEXITCODE\r\n"
        f"Set-Content -LiteralPath '{exit_path}' -Value $provisionExitCode -Encoding Ascii\r\n"
    )
    worker_encoded = base64.b64encode(worker_script.encode("utf-16le")).decode("ascii")
    launcher_script = (
        f"Start-Process -FilePath '{WINDOWS_POWERSHELL}' -ArgumentList @(" 
        "'-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',"
        f"'-EncodedCommand','{worker_encoded}'"
        ") -WindowStyle Hidden\r\n"
    )
    launch = sandbox.process.exec(_powershell_encoded(launcher_script), timeout=60)
    if launch.exit_code != 0:
        raise DaytonaError(f"failed to launch Windows provisioner: {launch.result}")

    deadline = time.monotonic() + timeout
    while True:
        time.sleep(WINDOWS_PROVISION_POLL_SECONDS)
        try:
            exit_text = _download_text(sandbox, exit_path, encoding="ascii")
        except Exception as error:
            if not _is_not_found(error):
                raise
        else:
            try:
                exit_code = int(exit_text.strip())
            except ValueError:
                raise DaytonaError(
                    f"Windows provisioner wrote an unreadable exit code: {exit_text!r}"
                ) from None
            try:
                result = _download_text(sandbox, log_path, encoding="utf-8")
            except Exception as error:
                if not _is_not_found(error):
                    raise
                result = ""
            return ExecuteResponse(exit_code=exit_code, result=result)

        if time.monotonic() >= deadline:
            raise DaytonaError(f"Windows provisioner timed out after {timeout} seconds")


def _unique_sandbox_name(purpose: str) -> str:
    return f"cursor-self-hosted-windows-{purpose}-{uuid.uuid4().hex[:12]}"


def _upload_snapshot_inputs(sandbox: Any, *, timeout: int) -> None:
    for source, destination in WINDOWS_SNAPSHOT_UPLOADS:
        sandbox.fs.upload_file(source.read_bytes(), destination, timeout=timeout)


def _raise_cleanup_failure(
    sandbox: Any,
    purpose: str,
    cleanup_error: Exception,
) -> None:
    name = getattr(sandbox, "name", "unknown")
    raise WindowsSnapshotCleanupError(
        f"Failed to delete Windows {purpose} sandbox {name}: {cleanup_error}"
    ) from cleanup_error


def _delete_sandbox(
    daytona: Any,
    sandbox: Any,
    *,
    timeout: int,
    purpose: str,
    primary_error: Exception | None,
) -> None:
    try:
        daytona.delete(sandbox, timeout=timeout)
    except Exception as cleanup_error:
        name = getattr(sandbox, "name", "unknown")
        if primary_error is not None:
            primary_error.add_note(
                f"Cleanup also failed for Windows {purpose} sandbox {name}: "
                f"{cleanup_error}"
            )
            return
        _raise_cleanup_failure(sandbox, purpose, cleanup_error)


def _verify_or_delete_snapshot(
    daytona: Any,
    snapshot: object,
    *,
    sandbox_timeout: int,
) -> None:
    name = str(getattr(snapshot, "name"))
    verifier: Any | None = None
    verifier_error: Exception | None = None
    try:
        verifier = daytona.create(
            CreateSandboxFromSnapshotParams(
                snapshot=name,
                name=_unique_sandbox_name("verifier"),
            ),
            timeout=sandbox_timeout,
        )
        _upload_snapshot_inputs(verifier, timeout=sandbox_timeout)
        verification = run_windows_provisioner(
            verifier,
            verify_only=True,
            timeout=sandbox_timeout,
        )
        if verification.exit_code != 0:
            raise DaytonaError(
                f"Windows snapshot verification failed with exit code "
                f"{verification.exit_code}: {verification.result}"
            )
    except Exception as error:
        verifier_error = error
        try:
            daytona.snapshot.delete(snapshot)
        except Exception as cleanup_error:
            error.add_note(
                f"Cleanup also failed for uncertified Windows snapshot "
                f"{name}: {cleanup_error}"
            )
        raise
    finally:
        if verifier is not None:
            _delete_sandbox(
                daytona,
                verifier,
                timeout=sandbox_timeout,
                purpose="verifier",
                primary_error=verifier_error,
            )


def build_windows_snapshot(
    daytona: Any,
    *,
    name: str,
    source_snapshot: str,
    build_timeout: int,
    sandbox_timeout: int,
) -> tuple[object, bool]:
    """Build and cold-verify a Windows snapshot, or reuse an active one."""
    reusable = _find_reusable_snapshot(daytona, name)
    if reusable is not None:
        _verify_or_delete_snapshot(
            daytona,
            reusable,
            sandbox_timeout=sandbox_timeout,
        )
        return reusable, True

    builder: Any | None = None
    builder_error: Exception | None = None
    builder_cleanup_error: Exception | None = None
    snapshot: Any
    try:
        builder = daytona.create(
            CreateSandboxFromSnapshotParams(
                snapshot=source_snapshot,
                name=_unique_sandbox_name("builder"),
            ),
            timeout=sandbox_timeout,
        )
        assert builder is not None
        _upload_snapshot_inputs(builder, timeout=sandbox_timeout)
        provision = run_windows_provisioner(
            builder,
            verify_only=False,
            timeout=build_timeout,
        )
        if provision.exit_code != 0:
            raise DaytonaError(
                f"Windows provisioning failed with exit code {provision.exit_code}: "
                f"{provision.result}"
            )

        builder.stop(timeout=sandbox_timeout)
        builder._experimental_create_snapshot(name, timeout=build_timeout)
        snapshot = daytona.snapshot.get(name)
        _validate_windows_snapshot(snapshot, name)
    except Exception as error:
        builder_error = error
        raise
    finally:
        if builder is not None:
            try:
                _delete_sandbox(
                    daytona,
                    builder,
                    timeout=sandbox_timeout,
                    purpose="builder",
                    primary_error=builder_error,
                )
            except Exception as error:
                builder_cleanup_error = error

    try:
        _verify_or_delete_snapshot(
            daytona,
            snapshot,
            sandbox_timeout=sandbox_timeout,
        )
    except Exception as error:
        if builder_cleanup_error is not None:
            error.add_note(str(builder_cleanup_error))
        raise
    if builder_cleanup_error is not None:
        raise builder_cleanup_error

    return snapshot, False
