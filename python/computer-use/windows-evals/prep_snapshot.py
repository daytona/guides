"""Prepare a derived Windows Daytona snapshot for the computer-use eval guide."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import Any, Sequence

from common import create_sandbox, get_client, ps_ok

PYTHON_VERSION = "3.13.9"
PYTHON_INSTALLER_URL = (
    "https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.exe"
)
PYTHON_INSTALLER_PATH = r"C:\python-installer.exe"
PYTHON_EXE = r"C:\Program Files\Python313\python.exe"
EVALS_DIR = r"C:\evals"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a Daytona Windows snapshot for the computer-use eval suite.",
    )
    parser.add_argument(
        "--base",
        default="windows-medium",
        help="base Windows snapshot to prepare (default: %(default)s)",
    )
    parser.add_argument(
        "--name",
        default="windows-cu-evals-v1",
        help="name for the derived snapshot (default: %(default)s)",
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="leave the preparation sandbox in place instead of deleting it",
    )
    parser.add_argument(
        "--skip-python",
        action="store_true",
        help="skip the Python installer step and only seed the eval directory before snapshotting",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    client = get_client()
    sandbox = None
    sandbox_name = _prep_sandbox_name(args.name)
    primary_error: BaseException | None = None

    try:
        print(f"[1/6] Creating preparation sandbox from {args.base!r}...", flush=True)
        sandbox = create_sandbox(
            client,
            args.base,
            name=sandbox_name,
            labels={
                "guide": "windows-cu-evals",
                "role": "prep-snapshot",
                "snapshot": args.name,
            },
        )
        print(f"      Sandbox ready: {sandbox.name} ({sandbox.id})", flush=True)

        if args.skip_python:
            print(f"[2/6] Skipping Python {PYTHON_VERSION} install (--skip-python).", flush=True)
        else:
            _install_python(sandbox)

        _delete_installer(sandbox)
        _seed_evals_dir(sandbox)

        print("[5/6] Stopping sandbox before creating a filesystem snapshot...", flush=True)
        sandbox.stop(timeout=300)

        print(f"      Creating snapshot {args.name!r} from stopped sandbox...", flush=True)
        sandbox._experimental_create_snapshot(args.name)

        print("      Waiting for snapshot to become active...", flush=True)
        _wait_for_snapshot_active(client, args.name, timeout_s=300)

        print(f"[6/6] Snapshot ready: {args.name}", flush=True)
        print(f"Usage hint: python harness.py --snapshot {args.name}", flush=True)
        return 0
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if sandbox is not None:
            if args.keep_sandbox:
                print(f"Keeping preparation sandbox: {sandbox.name} ({sandbox.id})", flush=True)
            else:
                print("Deleting preparation sandbox...", flush=True)
                try:
                    sandbox.delete(timeout=120)
                except Exception as exc:  # noqa: BLE001 - do not hide the primary failure.
                    if primary_error is None:
                        raise
                    print(f"Warning: failed to delete preparation sandbox: {exc}", file=sys.stderr, flush=True)


def _install_python(sandbox) -> None:
    print(f"[2/6] Downloading Python {PYTHON_VERSION} installer...", flush=True)
    _run_ps_step(
        sandbox,
        f"""
$ProgressPreference = 'SilentlyContinue'
Remove-Item -Force -ErrorAction SilentlyContinue '{PYTHON_INSTALLER_PATH}'
Invoke-WebRequest -Uri '{PYTHON_INSTALLER_URL}' -UseBasicParsing -TimeoutSec 300 -OutFile '{PYTHON_INSTALLER_PATH}'
(Get-Item '{PYTHON_INSTALLER_PATH}').Length
""".strip(),
        timeout=330,
        failure="Python installer download failed",
    )


    print("      Validating Python installer signature...", flush=True)
    _run_ps_step(
        sandbox,
        f"""
$signature = Get-AuthenticodeSignature -LiteralPath '{PYTHON_INSTALLER_PATH}'
if ($signature.Status -ne 'Valid') {{
    throw ('Python installer signature was ' + $signature.Status)
}}
$subject = $signature.SignerCertificate.Subject
if ($subject -notlike '*Python Software Foundation*') {{
    throw ('Unexpected Python installer signer: ' + $subject)
}}
'installer signature valid'
""".strip(),
        timeout=60,
        failure="Python installer signature validation failed",
    )

    # The GA Windows daemon drops individual exec requests that run past
    # roughly 25 seconds (observed empirically 2026-07-06: a ~25s installer
    # exec succeeded, a ~30s one died with an empty-body error). Launch the
    # installer without -Wait and poll with short execs instead.
    print("      Launching unattended Python installer...", flush=True)
    _run_ps_step(
        sandbox,
        f"""
$p = Start-Process -FilePath '{PYTHON_INSTALLER_PATH}' -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_test=0' -PassThru
"LaunchedPid=$($p.Id)"
""".strip(),
        timeout=60,
        failure="Python installer launch failed",
    )

    print("      Waiting for the installer to finish...", flush=True)
    deadline = time.monotonic() + 600
    last_state = "UNKNOWN"
    while True:
        ok, output = ps_ok(
            sandbox,
            f"""
$running = Get-Process -Name 'python-installer' -ErrorAction SilentlyContinue
if ($running) {{ 'RUNNING' }} elseif (Test-Path '{PYTHON_EXE}') {{ 'DONE' }} else {{ 'PENDING' }}
""".strip(),
            timeout=30,
        )
        if ok and output.strip():
            last_state = output.strip().splitlines()[-1].strip()
        if last_state == "DONE":
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f"Python install did not finish within 600s; last state {last_state!r}")
        time.sleep(5)

    _run_ps_step(
        sandbox,
        f"& '{PYTHON_EXE}' --version",
        timeout=60,
        failure="Python verification failed",
    )


def _delete_installer(sandbox) -> None:
    print(f"[3/6] Removing installer at {PYTHON_INSTALLER_PATH}...", flush=True)
    _run_ps_step(
        sandbox,
        f"""
if (Test-Path '{PYTHON_INSTALLER_PATH}') {{
    Remove-Item -Force '{PYTHON_INSTALLER_PATH}'
    'installer removed'
}} else {{
    'installer absent'
}}
""".strip(),
        timeout=60,
        failure="Installer cleanup failed",
    )


def _seed_evals_dir(sandbox) -> None:
    print(f"[4/6] Seeding {EVALS_DIR}...", flush=True)
    _run_ps_step(
        sandbox,
        f"""
New-Item -ItemType Directory -Force -Path '{EVALS_DIR}' | Out-Null
'{EVALS_DIR} ready'
""".strip(),
        timeout=60,
        failure="Eval directory setup failed",
    )


def _run_ps_step(sandbox, script: str, *, timeout: int, failure: str) -> str:
    ok, output = ps_ok(sandbox, script, timeout=timeout)
    if ok:
        summary = _last_nonempty_line(output)
        if summary:
            print(f"      {summary}", flush=True)
        return output
    detail = output or "no PowerShell output"
    raise RuntimeError(f"{failure}: {detail}")


def _wait_for_snapshot_active(client, name: str, *, timeout_s: int) -> Any:
    deadline = time.monotonic() + timeout_s
    last_state: str | None = None
    last_error: Exception | None = None

    while True:
        try:
            snapshot = client.snapshot.get(name)
        except Exception as exc:  # noqa: BLE001 - snapshots may 404 briefly after create.
            if not _is_transient_snapshot_lookup_error(exc):
                raise RuntimeError(f"snapshot lookup failed for {name!r}: {exc}") from exc
            last_error = exc
        else:
            last_error = None
            last_state = _state_name(_field(snapshot, "state"))
            if last_state == "active":
                return snapshot
            if last_state in {"error", "failed"}:
                raise RuntimeError(f"snapshot {name!r} entered state {last_state!r}")

        try:
            page = client.snapshot.list(limit=200)
        except Exception as exc:  # noqa: BLE001 - list may also race snapshot propagation.
            if not _is_transient_snapshot_lookup_error(exc):
                raise RuntimeError(f"snapshot list failed while waiting for {name!r}: {exc}") from exc
            last_error = exc
        else:
            for item in getattr(page, "items", []):
                if _field(item, "name") != name:
                    continue
                last_error = None
                last_state = _state_name(_field(item, "state"))
                if last_state == "active":
                    return item
                if last_state in {"error", "failed"}:
                    raise RuntimeError(f"snapshot {name!r} entered state {last_state!r}")
                break

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(5.0, remaining))

    if last_error is not None and last_state is None:
        raise TimeoutError(f"snapshot {name!r} did not become active within {timeout_s}s; last error: {last_error}")
    raise TimeoutError(f"snapshot {name!r} did not become active within {timeout_s}s; last state: {last_state!r}")


def _prep_sandbox_name(snapshot_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = f"-prep-{stamp}"
    safe = "".join(char.lower() if char.isalnum() else "-" for char in snapshot_name)
    safe = "-".join(part for part in safe.split("-") if part) or "windows-cu-evals"
    return f"{safe[: 63 - len(suffix)].rstrip('-')}{suffix}"


def _is_transient_snapshot_lookup_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status in {404, 409}:
        return True
    message = str(exc).lower()
    return "404" in message or "not found" in message or "not_found" in message


def _state_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
