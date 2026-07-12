"""Build the Windows snapshot with pinned CLI, browser, Git, and media tooling.

The default snapshot name is derived from the provisioner, source snapshot,
and resolved Devin CLI release.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.resources as resources
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path

import httpx
from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaError,
    ExecuteResponse,
    Sandbox,
)
from daytona_api_client import SnapshotState
from daytona_api_client.models.snapshot_dto import SnapshotDto
from dotenv import load_dotenv

from .sandbox import is_not_found


PROVISIONER = resources.files("devin_outposts").joinpath("provision_windows.ps1")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_SOURCE_SNAPSHOT = "windows-medium"
DEFAULT_SNAPSHOT_PREFIX = "devin-outposts-windows"
DEVIN_MANIFEST_URL = "https://static.devin.ai/cli/current/manifest.json"
DEVIN_WINDOWS_PLATFORM = "x86_64-pc-windows"
MANIFEST_TIMEOUT = 30.0
REMOTE_PROVISIONER = r"C:\Windows\Temp\provision_windows.ps1"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
SNAPSHOT_PAGE_LIMIT = 100
DEFAULT_BUILD_TIMEOUT = 1800
DEFAULT_SANDBOX_TIMEOUT = 300

EXIT_USAGE = 2
EXIT_OPERATION = 3
EXIT_COLLISION = 4
EXIT_COMMAND = 5
EXIT_CLEANUP = 6


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or reuse a provisioned Daytona Windows snapshot and verify it."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="dotenv file to load when it exists (default: repository .env)",
    )
    parser.add_argument(
        "--source-snapshot",
        default=DEFAULT_SOURCE_SNAPSHOT,
        help=f"Daytona snapshot used for the builder (default: {DEFAULT_SOURCE_SNAPSHOT})",
    )
    parser.add_argument(
        "--name",
        help="snapshot name (default: derived from the recipe, CLI release, and source snapshot)",
    )
    parser.add_argument(
        "--build-timeout",
        type=_positive_int,
        default=DEFAULT_BUILD_TIMEOUT,
        help="seconds allowed for provisioning and snapshot creation",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=_positive_int,
        default=DEFAULT_SANDBOX_TIMEOUT,
        help="seconds allowed for sandbox creation, verification, and cleanup",
    )
    parser.add_argument(
        "--create-serving-sandbox",
        action="store_true",
        help="retain the fresh verified sandbox instead of deleting it",
    )
    return parser.parse_args()


class DevinManifestError(RuntimeError):
    """Raised when the current Devin CLI release cannot be resolved."""


def _required_manifest_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DevinManifestError(f"Devin CLI manifest does not contain a valid {field}")
    return value.strip()


def _resolve_current_devin_cli(
    client: httpx.Client | None = None,
) -> tuple[str, str]:
    owns_client = client is None
    request_client = client or httpx.Client(timeout=MANIFEST_TIMEOUT)
    try:
        try:
            response = request_client.get(DEVIN_MANIFEST_URL)
        except httpx.RequestError as exc:
            raise DevinManifestError(
                "Could not reach the Devin CLI manifest endpoint"
            ) from exc
    finally:
        if owns_client:
            request_client.close()

    if response.status_code < 200 or response.status_code >= 300:
        raise DevinManifestError(
            f"Devin CLI manifest endpoint returned HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise DevinManifestError(
            "Devin CLI manifest endpoint returned invalid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise DevinManifestError("Devin CLI manifest is not a JSON object")

    version = _required_manifest_string(payload.get("version"), "version")
    platforms = payload.get("platforms")
    if not isinstance(platforms, Mapping):
        raise DevinManifestError(
            "Devin CLI manifest does not contain a platforms object"
        )
    windows = platforms.get(DEVIN_WINDOWS_PLATFORM)
    if not isinstance(windows, Mapping):
        raise DevinManifestError(
            f"Devin CLI manifest does not contain a {DEVIN_WINDOWS_PLATFORM} entry"
        )
    sha256 = _required_manifest_string(
        windows.get("sha256"),
        f"{DEVIN_WINDOWS_PLATFORM} SHA-256",
    ).lower()
    try:
        decoded_sha = bytes.fromhex(sha256)
    except ValueError as exc:
        raise DevinManifestError(
            f"Devin CLI manifest contains an invalid {DEVIN_WINDOWS_PLATFORM} SHA-256"
        ) from exc
    if len(sha256) != 64 or len(decoded_sha) != 32:
        raise DevinManifestError(
            f"Devin CLI manifest contains an invalid {DEVIN_WINDOWS_PLATFORM} SHA-256"
        )
    return version, sha256


def _snapshot_name(
    provisioner: Path,
    explicit_name: str | None,
    *,
    source_snapshot: str | None = None,
    devin_cli_version: str | None = None,
    devin_cli_sha256: str | None = None,
) -> str:
    if explicit_name is not None and explicit_name.strip():
        return explicit_name.strip()
    if source_snapshot is None or devin_cli_version is None or devin_cli_sha256 is None:
        raise ValueError(
            "default snapshot identity requires source snapshot and Devin CLI release"
        )

    digest = hashlib.sha256()
    for component in (
        b"devin-outposts-windows-snapshot-v2",
        provisioner.read_bytes(),
        source_snapshot.encode("utf-8"),
        devin_cli_version.encode("utf-8"),
        devin_cli_sha256.lower().encode("ascii"),
    ):
        digest.update(len(component).to_bytes(8, "big"))
        digest.update(component)
    return f"{DEFAULT_SNAPSHOT_PREFIX}-{digest.hexdigest()[:8]}"


def _iter_snapshots(daytona: Daytona) -> Iterator[SnapshotDto]:
    page = 1
    while True:
        result = daytona.snapshot.list(page=page, limit=SNAPSHOT_PAGE_LIMIT)
        yield from result.items
        if page >= result.total_pages:
            return
        page += 1


def _find_snapshot(daytona: Daytona, name: str) -> SnapshotDto | None:
    return next(
        (snapshot for snapshot in _iter_snapshots(daytona) if snapshot.name == name),
        None,
    )


def _unique_sandbox_name(purpose: str) -> str:
    return f"devin-outposts-win-{purpose}-{uuid.uuid4().hex[:12]}"


def _powershell_command(*, verify_only: bool) -> str:
    command = (
        f"{POWERSHELL} -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -File {REMOTE_PROVISIONER}"
    )
    if verify_only:
        command += " -VerifyOnly"
    return command


def _encoded_powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return (
        f"{POWERSHELL} -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -EncodedCommand {encoded}"
    )


def _run_provisioner(
    sandbox: Sandbox, *, verify_only: bool, timeout: int
) -> ExecuteResponse:
    """Run the provisioner detached and poll marker files with short execs.

    Daytona session commands never report exit codes or capture output on
    Windows sandboxes, and one synchronous exec would hold a single HTTP call
    open for the whole build. The provisioner therefore runs as a detached
    process that writes all output streams to a log file and its exit code to
    a marker file; each poll is an independent short filesystem read.
    """
    run_id = uuid.uuid4().hex
    # Forward slashes: PowerShell accepts them, and Daytona fs.download_file
    # on Windows sandboxes rejects backslash paths.
    log_path = f"C:/Windows/Temp/provision-{run_id}.log"
    exit_path = f"C:/Windows/Temp/provision-{run_id}.exitcode"

    worker_script = (
        f"& {_powershell_command(verify_only=verify_only)} *> '{log_path}'\r\n"
        f"Set-Content -LiteralPath '{exit_path}' -Value $LASTEXITCODE -Encoding Ascii\r\n"
    )
    worker_encoded = base64.b64encode(worker_script.encode("utf-16le")).decode("ascii")
    launcher_script = (
        "Start-Process -FilePath '" + POWERSHELL + "' -ArgumentList @("
        "'-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',"
        f"'-EncodedCommand','{worker_encoded}'"
        ") -WindowStyle Hidden\r\n"
    )
    launch = sandbox.process.exec(_encoded_powershell(launcher_script), timeout=60)
    if launch.exit_code != 0:
        raise DaytonaError(f"failed to launch Windows provisioner: {launch.result}")

    printed = 0

    def _print_new_output() -> str:
        nonlocal printed
        try:
            content = sandbox.fs.download_file(log_path)
        except Exception as exc:
            if isinstance(exc, FileNotFoundError) or is_not_found(exc):
                return ""
            raise
        if isinstance(content, bytes):
            # PowerShell 5.1 stream redirection writes UTF-16LE with a BOM.
            if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
                content = content.decode("utf-16", errors="replace")
            else:
                content = content.decode("utf-8", errors="replace")
        result = content or ""
        if len(result) > printed:
            print(result[printed:], end="", flush=True)
            printed = len(result)
        return result

    deadline = time.monotonic() + timeout
    while True:
        time.sleep(5)
        result = _print_new_output()
        try:
            exit_content = sandbox.fs.download_file(exit_path)
        except Exception as exc:
            if not isinstance(exc, FileNotFoundError) and not is_not_found(exc):
                raise
            exit_content = None
        if exit_content is not None:
            if isinstance(exit_content, bytes):
                exit_content = exit_content.decode("ascii", errors="replace")
            result = _print_new_output()
            if result and not result.endswith("\n"):
                print(flush=True)
            try:
                exit_code = int(exit_content.strip())
            except ValueError:
                raise DaytonaError(
                    f"Windows provisioner wrote an unreadable exit code: {exit_content!r}"
                ) from None
            return ExecuteResponse(exit_code=exit_code, result=result)

        if time.monotonic() >= deadline:
            raise DaytonaError(f"Windows provisioner timed out after {timeout} seconds")


def _verify_computer_use(sandbox: Sandbox) -> bool:
    try:
        start = sandbox.computer_use.start()
        status = sandbox.computer_use.get_status()
        screenshot = sandbox.computer_use.screenshot.take_full_screen(show_cursor=True)
        encoded = screenshot.screenshot or ""
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        image = base64.b64decode(encoded, validate=True)
    except (DaytonaError, ValueError, binascii.Error) as exc:
        print(f"Windows Computer Use verification failed: {exc}", file=sys.stderr)
        return False

    status_value = str(status.status or "").lower()
    if status_value != "active":
        print(
            f"Windows Computer Use status is {status.status!r}; expected 'active'",
            file=sys.stderr,
        )
        return False
    if not image:
        print("Windows Computer Use screenshot was empty", file=sys.stderr)
        return False
    print(
        "Windows Computer Use verified: "
        f"message={start.message!r} status={status_value} screenshot_bytes={len(image)}"
    )
    return True


def _delete_sandbox(
    daytona: Daytona, sandbox: Sandbox, timeout: int, purpose: str
) -> bool:
    try:
        daytona.delete(sandbox, timeout=timeout)
    except DaytonaError as exc:
        print(
            f"Failed to delete {purpose} sandbox {sandbox.name}: {exc}", file=sys.stderr
        )
        return False
    return True


def main() -> int:
    args = _parse_args()

    if not PROVISIONER.is_file():
        print(f"Missing provisioner: {PROVISIONER}", file=sys.stderr)
        return EXIT_USAGE

    if args.env_file.is_file():
        load_dotenv(args.env_file, override=False)
    elif args.env_file != DEFAULT_ENV_FILE:
        print(f"Environment file does not exist: {args.env_file}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if args.name is not None and args.name.strip():
            name = _snapshot_name(PROVISIONER, args.name)
        else:
            devin_cli_version, devin_cli_sha256 = _resolve_current_devin_cli()
            name = _snapshot_name(
                PROVISIONER,
                None,
                source_snapshot=args.source_snapshot,
                devin_cli_version=devin_cli_version,
                devin_cli_sha256=devin_cli_sha256,
            )
    except DevinManifestError as exc:
        print(f"Unable to resolve current Devin CLI release: {exc}", file=sys.stderr)
        return EXIT_OPERATION
    except (OSError, ValueError) as exc:
        print(
            f"Unable to derive snapshot identity from {PROVISIONER}: {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        daytona = Daytona()
        snapshot = _find_snapshot(daytona, name)
    except DaytonaError as exc:
        print(f"Unable to inspect Daytona snapshots: {exc}", file=sys.stderr)
        return EXIT_OPERATION

    cleanup_failed = False

    if snapshot is not None:
        if snapshot.state != SnapshotState.ACTIVE:
            print(
                f"Snapshot name collision: {snapshot.name} state={snapshot.state.value}; expected active",
                file=sys.stderr,
            )
            return EXIT_COLLISION
        print(f"Reusing snapshot: {snapshot.name} state={snapshot.state.value}")
    else:
        builder: Sandbox | None = None
        build_failed = False
        try:
            builder = daytona.create(
                CreateSandboxFromSnapshotParams(
                    snapshot=args.source_snapshot,
                    name=_unique_sandbox_name("builder"),
                ),
                timeout=args.sandbox_timeout,
            )
            builder.fs.upload_file(
                str(PROVISIONER),
                REMOTE_PROVISIONER,
                timeout=args.sandbox_timeout,
            )
            provision = _run_provisioner(
                builder,
                verify_only=False,
                timeout=args.build_timeout,
            )
            if provision.exit_code != 0:
                print(
                    f"Windows provisioning failed with exit code {provision.exit_code}",
                    file=sys.stderr,
                )
                build_failed = True
            else:
                builder.stop(timeout=args.sandbox_timeout)
                builder._experimental_create_snapshot(name, timeout=args.build_timeout)
                snapshot = daytona.snapshot.get(name)
                if snapshot.state != SnapshotState.ACTIVE:
                    print(
                        f"Created snapshot is not ACTIVE: {snapshot.name} state={snapshot.state.value}",
                        file=sys.stderr,
                    )
                    build_failed = True
        except DaytonaError as exc:
            print(f"Windows snapshot build failed: {exc}", file=sys.stderr)
            build_failed = True
        finally:
            if builder is not None and not _delete_sandbox(
                daytona, builder, args.sandbox_timeout, "builder"
            ):
                cleanup_failed = True

        if build_failed or snapshot is None:
            return EXIT_CLEANUP if cleanup_failed else EXIT_COMMAND

    verifier: Sandbox | None = None
    retain_verifier = False
    verification_failed = False
    purpose = "serving" if args.create_serving_sandbox else "verifier"
    try:
        verifier = daytona.create(
            CreateSandboxFromSnapshotParams(
                snapshot=snapshot.name,
                name=_unique_sandbox_name(purpose),
                auto_stop_interval=0 if args.create_serving_sandbox else None,
                auto_delete_interval=-1 if args.create_serving_sandbox else None,
            ),
            timeout=args.sandbox_timeout,
        )
        verifier.fs.upload_file(
            str(PROVISIONER),
            REMOTE_PROVISIONER,
            timeout=args.sandbox_timeout,
        )
        verification = _run_provisioner(
            verifier,
            verify_only=True,
            timeout=args.sandbox_timeout,
        )
        if verification.exit_code != 0:
            print(
                f"Windows snapshot verification failed with exit code {verification.exit_code}",
                file=sys.stderr,
            )
            verification_failed = True
        elif not _verify_computer_use(verifier):
            verification_failed = True
        else:
            retain_verifier = args.create_serving_sandbox
    except DaytonaError as exc:
        print(f"Windows snapshot verification failed: {exc}", file=sys.stderr)
        verification_failed = True
    finally:
        if verifier is not None and not retain_verifier:
            if not _delete_sandbox(daytona, verifier, args.sandbox_timeout, "verifier"):
                cleanup_failed = True

    if cleanup_failed:
        return EXIT_CLEANUP
    if verification_failed:
        return EXIT_COMMAND

    print(f"Snapshot ready: {snapshot.name} state={snapshot.state.value}")
    if retain_verifier and verifier is not None:
        print(f"Serving sandbox retained: id={verifier.id} name={verifier.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
