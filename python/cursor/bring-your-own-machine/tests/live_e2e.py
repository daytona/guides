#!/usr/bin/env python3
"""Run one real Cursor pool request through one Daytona sandbox class."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from daytona import Daytona, DaytonaConfig, ListSandboxesQuery

from cursor_byom.worker_windows import (
    WINDOWS_WORKER_PID_PATH,
    powershell_encoded,
    windows_inspection_command,
)

TERMINAL_RUN_STATES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
LINUX_MARKER_PATH = "/home/daytona/workspace/cursor-byom-live-marker.txt"
WINDOWS_MARKER_PATH = r"C:\cursor\workspace\cursor-byom-live-marker.txt"
LINUX_PID_PATH = "/tmp/cursor-byom/worker.pid"
POLL_SECONDS = 3.0


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run one real Cursor request in one Daytona sandbox class.",
        epilog=(
            "Example:\n"
            "  python tests/live_e2e.py --sandbox-class linux-vm "
            "--target eu-central-1 --snapshot cursor-byom-linux-vm-abcd1234"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument(
        "--sandbox-class",
        choices=("container", "linux-vm", "windows"),
        required=True,
    )
    result.add_argument("--target", required=True)
    result.add_argument("--snapshot", required=True)
    result.add_argument(
        "--timeout",
        type=positive_int,
        default=1200,
        help="total seconds allowed for the Cursor run (default: 1200)",
    )
    result.add_argument(
        "--agent",
        default=shutil.which("agent"),
        help="Cursor Agent CLI path (default: agent from PATH)",
    )
    result.add_argument(
        "--spawn",
        default=str(
            Path(__file__).resolve().parents[1]
            / ".venv/bin/spawn-cursor-byom-worker"
        ),
        help="spawn-cursor-byom-worker path",
    )
    return result


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def cursor_request(
    api_key: str,
    method: str,
    path: str,
    payload: object | None = None,
) -> object:
    body = None
    headers = {
        "Authorization": "Basic "
        + base64.b64encode(f"{api_key}:".encode()).decode(),
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        "https://api.cursor.com" + path,
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(
            f"Cursor {method} {path} returned HTTP {error.code}: {detail}"
        ) from error
    if not content:
        return {}
    return json.loads(content)


def is_not_found(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        return False
    try:
        return int(status_code) == 404
    except (TypeError, ValueError):
        return False


def decode_text(content: object) -> str:
    if isinstance(content, bytes):
        if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return content.decode("utf-16", errors="replace")
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def find_sandbox(daytona: Daytona, pool: str) -> Any | None:
    sandboxes = list(
        daytona.list(
            ListSandboxesQuery(labels={"cursor.pool": pool})
        )
    )
    if not sandboxes:
        return None
    if len(sandboxes) != 1:
        names = sorted(str(item.name) for item in sandboxes)
        raise RuntimeError(f"Pool {pool} has multiple sandboxes: {names}")
    return sandboxes[0]


def marker_path(sandbox_class: str) -> str:
    return WINDOWS_MARKER_PATH if sandbox_class == "windows" else LINUX_MARKER_PATH


def read_marker(sandbox: Any, sandbox_class: str) -> str | None:
    path = marker_path(sandbox_class)
    if sandbox_class == "windows":
        path = path.replace("\\", "/")
    try:
        return decode_text(sandbox.fs.download_file(path)).strip()
    except Exception as error:
        if is_not_found(error) or isinstance(error, FileNotFoundError):
            return None
        raise


def read_pid(sandbox: Any, sandbox_class: str) -> str:
    path = WINDOWS_WORKER_PID_PATH if sandbox_class == "windows" else LINUX_PID_PATH
    if sandbox_class == "windows":
        path = path.replace("\\", "/")
    value = decode_text(sandbox.fs.download_file(path)).strip()
    if not value.isdigit() or int(value) <= 0:
        raise RuntimeError(f"Worker PID file contains {value!r}")
    return value


def worker_is_live(sandbox: Any, sandbox_class: str, pid: str) -> bool:
    if sandbox_class == "windows":
        response = sandbox.process.exec(windows_inspection_command(pid), timeout=30)
        return (
            getattr(response, "exit_code", 1) == 0
            and "running" in str(getattr(response, "result", "")).lower()
        )
    inner = (
        f"pid={pid}; "
        'kill -0 "$pid" 2>/dev/null; '
        'stat=$(cat "/proc/$pid/stat" 2>/dev/null); '
        "fields=${stat##*) }; "
        "state=${fields%% *}; "
        'test "$state" != Z'
    )
    command = f"sh -c {shlex.quote(inner)}"
    response = sandbox.process.exec(command, timeout=30)
    return getattr(response, "exit_code", 1) == 0


def stop_worker(sandbox: Any, sandbox_class: str, pid: str) -> None:
    if sandbox_class == "windows":
        command = powershell_encoded(
            f"Stop-Process -Id {pid} -Force -ErrorAction Stop"
        )
    else:
        command = f"sh -c 'kill {pid}'"
    response = sandbox.process.exec(command, timeout=30)
    if getattr(response, "exit_code", 1) != 0:
        raise RuntimeError(f"Failed to stop worker PID {pid}")


def wait_for_deletion(daytona: Daytona, sandbox_id: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            daytona.get(sandbox_id)
        except Exception as error:
            if is_not_found(error):
                return
            raise
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"Sandbox {sandbox_id} was not deleted after worker exit")


def terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.agent or not Path(args.agent).is_file():
        parser().error("--agent must name the Cursor Agent executable")
    if not Path(args.spawn).is_file():
        parser().error("--spawn must name spawn-cursor-byom-worker")

    daytona_key = required_secret("DAYTONA_API_KEY")
    cursor_key = required_secret("CURSOR_API_KEY")
    token = secrets.token_hex(16)
    pool = f"daytona-{args.sandbox_class.replace('-', '')}-{token[:8]}"
    agent_id: str | None = None
    run_id: str | None = None
    sandbox: Any | None = None
    controller: subprocess.Popen[str] | None = None
    run_payload: dict[str, Any] | None = None
    deadline = time.monotonic() + args.timeout

    with tempfile.TemporaryDirectory(prefix="cursor-byom-live-") as temp_dir:
        stdout_path = Path(temp_dir, "controller.stdout.log")
        stderr_path = Path(temp_dir, "controller.stderr.log")
        stdout_file = stdout_path.open("w")
        stderr_file = stderr_path.open("w")
        daytona = Daytona(
            DaytonaConfig(api_key=daytona_key, target=args.target)
        )
        try:
            cursor_request(
                cursor_key,
                "POST",
                "/v0/private-workers/pools",
                {"scope": "team", "poolName": pool},
            )
            controller_env = {
                **os.environ,
                "CURSOR_API_KEY": cursor_key,
                "DAYTONA_API_KEY": daytona_key,
                "DAYTONA_TARGET": args.target,
                "SNAPSHOT_NAME": args.snapshot,
                "CURSOR_WORKER_IDLE_RELEASE_TIMEOUT": "600",
                "MONITOR_POLL_SECONDS": "2",
                "SANDBOX_CREATE_TIMEOUT_SECONDS": "300",
                "SANDBOX_LAUNCH_TIMEOUT_SECONDS": "180",
            }
            controller = subprocess.Popen(
                [
                    args.agent,
                    "worker",
                    "controller",
                    "--spawn",
                    args.spawn,
                    "--pool",
                    pool,
                ],
                env=controller_env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )
            created = cursor_request(
                cursor_key,
                "POST",
                "/v1/agents",
                {
                    "name": f"Daytona {args.sandbox_class} live E2E",
                    "prompt": {
                        "text": (
                            f"Create {marker_path(args.sandbox_class)} with the exact "
                            f"text {token} and no trailing newline. Read the file back. "
                            "Do not change any other file."
                        )
                    },
                    "env": {"type": "pool", "name": pool},
                },
            )
            if not isinstance(created, dict):
                raise RuntimeError("Cursor create-agent response is not an object")
            agent_id = str(created["agent"]["id"])
            run_id = str(created["run"]["id"])

            marker_value: str | None = None
            while time.monotonic() < deadline:
                if controller.poll() is not None:
                    raise RuntimeError(
                        f"Controller exited with status {controller.returncode}"
                    )
                run = cursor_request(
                    cursor_key,
                    "GET",
                    f"/v1/agents/{urllib.parse.quote(agent_id)}/runs/"
                    f"{urllib.parse.quote(run_id)}",
                )
                if not isinstance(run, dict):
                    raise RuntimeError("Cursor run response is not an object")
                run_payload = run
                sandbox = sandbox or find_sandbox(daytona, pool)
                if sandbox is not None:
                    marker_value = read_marker(sandbox, args.sandbox_class)
                status = str(run.get("status", ""))
                if status in TERMINAL_RUN_STATES:
                    if status != "FINISHED":
                        raise RuntimeError(
                            f"Cursor run ended with {status}: {run.get('result', '')}"
                        )
                    if marker_value == token:
                        break
                time.sleep(POLL_SECONDS)
            else:
                raise TimeoutError("Cursor run did not finish before the deadline")

            if sandbox is None:
                raise RuntimeError("Cursor run created no Daytona sandbox")
            if str(getattr(sandbox, "sandbox_class", "")) not in (
                args.sandbox_class,
                f"SandboxClass.{args.sandbox_class.upper().replace('-', '_')}",
            ):
                actual = getattr(sandbox, "sandbox_class", None)
                actual = getattr(actual, "value", actual)
                if str(actual) != args.sandbox_class:
                    raise RuntimeError(
                        f"Daytona created sandbox class {actual!r}, expected {args.sandbox_class}"
                    )
            if read_marker(sandbox, args.sandbox_class) != token:
                raise RuntimeError("Cursor run did not write the exact marker token")

            pid = read_pid(sandbox, args.sandbox_class)
            if not worker_is_live(sandbox, args.sandbox_class, pid):
                raise RuntimeError(f"Worker PID {pid} is not live after the run")
            sandbox_id = str(sandbox.id)
            stop_worker(sandbox, args.sandbox_class, pid)
            wait_for_deletion(
                daytona,
                sandbox_id,
                min(deadline, time.monotonic() + 180),
            )
            sandbox = None

            result = {
                "agent_id": agent_id,
                "pool": pool,
                "run_id": run_id,
                "run_status": run_payload["status"] if run_payload else None,
                "sandbox_class": args.sandbox_class,
                "snapshot_name": args.snapshot,
                "target": args.target,
                "worker_cleanup": "deleted",
            }
            print(json.dumps(result, sort_keys=True))
            return 0
        except Exception as error:
            stdout_file.flush()
            stderr_file.flush()
            controller_logs = (
                stdout_path.read_text(errors="replace")
                + "\n"
                + stderr_path.read_text(errors="replace")
            )
            for secret_value in (daytona_key, cursor_key):
                controller_logs = controller_logs.replace(
                    secret_value, "<redacted>"
                )
            print(f"live E2E failed: {error}", file=sys.stderr)
            if controller_logs.strip():
                print(controller_logs[-8000:], file=sys.stderr)
            return 1
        finally:
            terminate_process(controller)
            if sandbox is not None:
                try:
                    daytona.delete(sandbox, timeout=300)
                except Exception:
                    pass
            if agent_id is not None:
                try:
                    cursor_request(
                        cursor_key,
                        "DELETE",
                        f"/v1/agents/{urllib.parse.quote(agent_id)}",
                    )
                except Exception:
                    pass
            try:
                query = urllib.parse.urlencode(
                    {"scope": "team", "pool_name": pool}
                )
                cursor_request(
                    cursor_key,
                    "DELETE",
                    f"/v0/private-workers/pools?{query}",
                )
            except Exception:
                pass
            stdout_file.close()
            stderr_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
