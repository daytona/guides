"""Dispatch worker lifecycle operations by sandbox platform.

Secrets pass through ``process.exec(env=...)`` and are never interpolated into
command strings.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from dataclasses import dataclass, replace
from typing import Any, Mapping

import httpx

from .config import Config
from .queue import QueueEntry
from .queue_shapes import claim_status_value, entry_platform
from .sandbox import sandbox_name_for
from .worker_linux import (
    LINUX_REMOTE_CACHE_DIR,
    linux_remote_filename,
    start_linux_worker_process,
    worker_paths,
)
from .worker_windows import (
    WINDOWS_REMOTE_CACHE_DIR,
    download_windows_text,
    powershell_encoded,
    ps_quote,
    start_windows_worker_process,
    windows_worker_paths,
)

REMOTE_BASE_URL = "https://static.devin.ai/devin-rs/remote"
LOGGER = logging.getLogger(__name__)

# The current Daytona Python SDK exposes long-running process sessions, but the
# session command API does not accept per-command environment variables. The
# worker token must not be interpolated into a command string, so this helper
# uses process.exec(env=...) to launch a background shell process safely. When
# SDK run_async sessions support per-command env, this helper can switch to that.


@dataclass(frozen=True)
class WorkerHandle:
    sandbox_name: str
    pid: str
    pid_path: str
    log_path: str
    platform: str = "linux"
    remote_sha: str = ""


def start_worker_process(
    sandbox: Any,
    config: Config,
    session_id: str,
    entry: Any,
    claim: QueueEntry | Mapping[str, Any],
) -> WorkerHandle:
    remote_sha = str(getattr(entry, "remote_binary_sha", "") or "")
    if entry_platform(entry) == "windows":
        handle = start_windows_worker_process(sandbox, config, session_id, entry, claim)
    else:
        handle = start_linux_worker_process(sandbox, config, session_id, entry, claim)
    return replace(handle, remote_sha=remote_sha)


def _claim_connection(
    entry: Any, claim: QueueEntry | Mapping[str, Any]
) -> tuple[str, str, str]:
    remote_sha = str(getattr(entry, "remote_binary_sha", "") or "")
    if not remote_sha:
        raise RuntimeError("queue entry has no pinned devin-remote SHA")
    gateway_url = claim_status_value(
        claim, "gateway_url", "gatewayUrl"
    ) or os.environ.get("DEVIN_OUTPOST_GATEWAY_URL", "")
    connect_token = claim_status_value(claim, "connect_token", "connectToken")
    if not gateway_url or not connect_token:
        raise RuntimeError(
            "claim response omitted the gateway URL or connect token; "
            "set DEVIN_OUTPOST_GATEWAY_URL to provide a gateway fallback"
        )
    return remote_sha, gateway_url, connect_token


def attach_worker_process(
    sandbox: Any,
    config: Config,
    session_id: str,
    *,
    platform: str = "linux",
    remote_sha: str | None = None,
) -> WorkerHandle | None:
    if not remote_sha:
        return None
    sandbox_name = sandbox_name_for(session_id)
    if platform == "windows":
        pid_path, log_path = windows_worker_paths(session_id)
    else:
        pid_path, log_path = worker_paths(session_id)
    handle = WorkerHandle(
        sandbox_name=sandbox_name,
        pid="",
        pid_path=pid_path,
        log_path=log_path,
        platform=platform,
        remote_sha=remote_sha,
    )
    worker_state = poll_worker_process(sandbox, config, handle)
    if worker_state is False:
        return None
    if worker_state is None:
        return handle
    try:
        if platform == "windows":
            pid = parse_pid(download_windows_text(sandbox, pid_path))
        else:
            pid = read_worker_pid(sandbox, pid_path)
    except Exception as exc:
        LOGGER.warning(
            "Worker PID read failed for %s: %s", sandbox_name, config.redacted(exc)
        )
        return handle
    return replace(handle, pid=pid or "unknown")


def poll_worker_process(
    sandbox: Any, config: Config, worker: WorkerHandle
) -> bool | None:
    if worker.platform == "windows":
        process_check = (
            f"$pidValue = Get-Content -LiteralPath {ps_quote(worker.pid_path)} "
            "-ErrorAction SilentlyContinue; "
            "$process = if ($pidValue) { Get-Process -Id $pidValue -ErrorAction SilentlyContinue }; "
        )
        if worker.remote_sha:
            executable = (
                rf"{WINDOWS_REMOTE_CACHE_DIR}\{worker.remote_sha}\devin-remote.exe"
            )
            process_check += (
                "if (-not $pidValue -or -not $process) { 'exited' } "
                "elseif (-not $process.Path) { 'unknown' } "
                f"elseif ([string]::Equals($process.Path, {ps_quote(executable)}, "
                "[System.StringComparison]::OrdinalIgnoreCase)) { 'running' } "
                "else { 'exited' }"
            )
        else:
            process_check += (
                "if ($pidValue -and $process) { 'running' } else { 'exited' }"
            )
        command = powershell_encoded(process_check)
    else:
        expected_executable = ""
        if worker.remote_sha:
            expected_executable = (
                f"{LINUX_REMOTE_CACHE_DIR}/{linux_remote_filename(worker.remote_sha)}"
            )
        script = (
            f"pid=$(cat {shlex.quote(worker.pid_path)} 2>/dev/null || true); "
            "case \"$pid\" in ''|*[!0-9]*) echo exited;; *) "
            'if ! kill -0 "$pid" 2>/dev/null; then echo exited; '
        )
        if expected_executable:
            script += (
                'else executable=$(readlink -f "/proc/$pid/exe" 2>/dev/null || true); '
                'if [ -z "$executable" ]; then echo unknown; '
                f'elif [ "$executable" = {shlex.quote(expected_executable)} ]; '
                "then echo running; else echo exited; fi; "
            )
        else:
            script += "else echo running; "
        script += "fi;; esac"
        command = f"sh -lc {shlex.quote(script)}"
    try:
        response = sandbox.process.exec(command, timeout=15)
    except Exception as exc:
        LOGGER.warning(
            "Worker poll failed for %s: %s", worker.sandbox_name, config.redacted(exc)
        )
        return None
    if getattr(response, "exit_code", 1) != 0:
        LOGGER.warning("Worker poll command failed for %s", worker.sandbox_name)
        return None
    state = str(getattr(response, "result", "") or "").strip().lower()
    if state == "running":
        return True
    if state == "exited":
        return False
    LOGGER.warning("Worker poll returned an unknown state for %s", worker.sandbox_name)
    return None


def read_worker_pid(sandbox: Any, pid_path: str) -> str | None:
    response = sandbox.process.exec(
        f"cat {shlex.quote(pid_path)} 2>/dev/null || true", timeout=10
    )
    return parse_pid(getattr(response, "result", ""))


def fetch_remote_checksum(filename: str) -> str:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(f"{REMOTE_BASE_URL}/{filename}.sha256")
        response.raise_for_status()
    return parse_sha256(response.text)


def parse_sha256(value: str) -> str:
    match = re.search(r"(?i)\b[0-9a-f]{64}\b", value)
    if not match:
        raise ValueError("checksum response did not contain a SHA-256 digest")
    return match.group(0).lower()


def parse_pid(output: str) -> str | None:
    match = re.search(r"\b(\d+)\b", output)
    return match.group(1) if match else None
