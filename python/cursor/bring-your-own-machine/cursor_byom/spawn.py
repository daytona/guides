"""Create one Daytona sandbox for a claimed Cursor request."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaConfig

from .config import (
    Config,
    redact,
    sandbox_labels,
    sandbox_name_for,
    worker_command,
    worker_environment,
)

_CURSOR_API_BASE = "https://api.cursor.com"
_PROC_ROOT = "/proc"
_WORKER_PID_PATH = "/tmp/cursor-byom/worker.pid"
_WORKER_LOG_PATH = "/tmp/cursor-byom/worker.log"
_WORKER_STARTUP_DELAY_SECONDS = 0.1
_SANDBOX_DELETION_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class SpawnResult:
    """Identifiers for a started Cursor worker."""

    sandbox_id: str
    sandbox_name: str
    worker_id: str
    request_id: str


def _is_not_found(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        return False
    try:
        return int(status_code) == 404
    except (TypeError, ValueError):
        return False


def _worker_launch_command(config: Config) -> str:
    command = shlex.join(worker_command(config))
    pid_path = shlex.quote(_WORKER_PID_PATH)
    proc_root = shlex.quote(_PROC_ROOT)
    inner = " && ".join(
        (
            "mkdir -p /tmp/cursor-byom",
            (
                f"(nohup {command} > {shlex.quote(_WORKER_LOG_PATH)} 2>&1 "
                f"< /dev/null & echo $! > {pid_path})"
            ),
            f"sleep {_WORKER_STARTUP_DELAY_SECONDS}",
            f"pid=$(cat {pid_path})",
            'case "$pid" in ""|*[!0-9]*) exit 1;; esac',
            'test "$pid" -gt 0',
            'kill -0 "$pid" 2>/dev/null',
            f'stat=$(cat {proc_root}/"$pid"/stat 2>/dev/null)',
            'fields=${stat##*) }',
            'state=${fields%% *}',
            'test "$state" != Z',
            'printf \'%s\\n\' "$pid"',
        )
    )
    return f"sh -c {shlex.quote(inner)}"


def _parse_worker_pid(value: object) -> str:
    pid = str(value).strip()
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError("Cursor worker launch did not return a numeric process ID")
    return pid


def _cursor_api_base(config: Config) -> str:
    for candidate in (config.cursor_api_url, config.cursor_api_endpoint):
        if candidate:
            parsed = urllib.parse.urlsplit(candidate)
            if parsed.scheme and parsed.netloc:
                return candidate.rstrip("/")
    return _CURSOR_API_BASE


def release_claim(config: Config, request_id: str) -> None:
    """Release one Cursor claim after its Daytona worker failed to start."""

    encoded_request_id = urllib.parse.quote(request_id, safe="")
    url = (
        f"{_cursor_api_base(config)}/v0/private-workers/claims/"
        f"{encoded_request_id}/release"
    )
    credentials = base64.b64encode(
        f"{config.cursor_api_key}:".encode("utf-8")
    ).decode("ascii")
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"Authorization": f"Basic {credentials}"},
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def start_monitor(config: Config, sandbox_id: str, worker_pid: str) -> None:
    """Start the host cleanup monitor without forwarding Cursor credentials."""

    monitor_environment = {
        "DAYTONA_API_KEY": config.daytona_api_key,
        "SANDBOX_ID": sandbox_id,
        "WORKER_PID": worker_pid,
        "MONITOR_POLL_SECONDS": str(config.monitor_poll_seconds),
    }
    subprocess.Popen(
        [sys.executable, "-m", "cursor_byom.monitor"],
        env=monitor_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def spawn_worker(
    config: Config,
    daytona: Any,
    *,
    release_claim: Callable[[str], None],
    start_monitor: Callable[[Config, str, str], None],
) -> SpawnResult:
    """Replace the deterministic sandbox, then launch its Cursor worker."""

    sandbox_name = sandbox_name_for(config.cursor_agent_worker_id)
    sandbox_to_cleanup: Any | None = None

    try:
        try:
            existing_sandbox = daytona.get(sandbox_name)
        except Exception as error:
            if not _is_not_found(error):
                raise
        else:
            existing_sandbox.delete(timeout=config.sandbox_create_timeout_seconds)
            deadline = time.monotonic() + config.sandbox_create_timeout_seconds
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for deleted sandbox {sandbox_name!r} "
                        "to become absent before creating its replacement"
                    )
                try:
                    daytona.get(sandbox_name)
                except Exception as error:
                    if _is_not_found(error):
                        break
                    raise
                time.sleep(_SANDBOX_DELETION_POLL_SECONDS)

        auto_stop_minutes = max(
            1, math.ceil(config.idle_release_timeout_seconds / 60)
        )
        sandbox = daytona.create(
            CreateSandboxFromSnapshotParams(
                name=sandbox_name,
                snapshot=config.snapshot_name,
                labels=sandbox_labels(config),
                auto_stop_interval=auto_stop_minutes,
                auto_delete_interval=0,
            ),
            timeout=config.sandbox_create_timeout_seconds,
        )
        sandbox_to_cleanup = sandbox

        response = sandbox.process.exec(
            _worker_launch_command(config),
            cwd="/home/daytona/workspace",
            env=worker_environment(config),
            timeout=config.sandbox_launch_timeout_seconds,
        )
        if getattr(response, "exit_code", 1) != 0:
            raise RuntimeError("Cursor worker process failed to launch")
        worker_pid = _parse_worker_pid(getattr(response, "result", ""))
        start_monitor(config, str(sandbox.id), worker_pid)
    except Exception:
        try:
            release_claim(config.cursor_request_id)
        except Exception as cleanup_error:
            print(
                "warning: failed to release Cursor request claim: "
                f"{_error_message(cleanup_error, config)}",
                file=sys.stderr,
            )
        if sandbox_to_cleanup is not None:
            try:
                sandbox_to_cleanup.delete(
                    timeout=config.sandbox_create_timeout_seconds
                )
            except Exception as cleanup_error:
                print(
                    "warning: failed to delete fresh Daytona sandbox: "
                    f"{_error_message(cleanup_error, config)}",
                    file=sys.stderr,
                )
        raise

    return SpawnResult(
        sandbox_id=str(sandbox.id),
        sandbox_name=sandbox_name,
        worker_id=config.cursor_agent_worker_id,
        request_id=config.cursor_request_id,
    )


def _error_message(error: BaseException, config: Config | None) -> str:
    secrets: tuple[str, ...] = ()
    if config is not None:
        secrets = (config.daytona_api_key, config.cursor_api_key)
    return redact(str(error), secrets)


def main(argv: list[str] | None = None) -> int:
    """Run the non-interactive worker spawn command."""

    parser = argparse.ArgumentParser(
        prog="spawn-cursor-byom-worker",
        description="Start or reuse a Cursor worker in a Daytona sandbox.",
        epilog=(
            "Example value for the controller --spawn option:\n"
            "  spawn-cursor-byom-worker"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.parse_args(argv)

    config: Config | None = None
    try:
        parsed_config = Config.from_env(os.environ)
        config = parsed_config
        daytona = Daytona(DaytonaConfig(api_key=parsed_config.daytona_api_key))
        result = spawn_worker(
            parsed_config,
            daytona,
            release_claim=lambda request_id: release_claim(
                parsed_config, request_id
            ),
            start_monitor=start_monitor,
        )
    except Exception as error:
        print(
            "spawn-cursor-byom-worker: failed to start worker: "
            f"{_error_message(error, config)}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "sandbox_id": result.sandbox_id,
                "sandbox_name": result.sandbox_name,
                "worker_id": result.worker_id,
                "request_id": result.request_id,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
