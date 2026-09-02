#!/usr/bin/env python3
"""Run one real Cursor request through one Daytona sandbox class."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaConfig,
    ListSandboxesQuery,
)

from cursor_self_hosted.config import Config, worker_environment
from cursor_self_hosted.spawn import _parse_worker_pid, start_monitor
from cursor_self_hosted.worker_windows import (
    WINDOWS_AGENT_INDEX_PATH,
    WINDOWS_LAUNCH_CONFIG_PATH,
    WINDOWS_WORKER_PID_PATH,
    WINDOWS_WORKER_STDERR_PATH,
    WINDOWS_WORKER_STDOUT_PATH,
    WINDOWS_WORKSPACE_PATH,
    _bootstrap_launcher,
    powershell_encoded,
    windows_inspection_command,
)

TERMINAL_RUN_STATES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
LINUX_MARKER_PATH = "/home/daytona/workspace/.cursor-self-hosted-live-marker.txt"
WINDOWS_MARKER_PATH = r"C:\cursor\workspace\.cursor-self-hosted-live-marker.txt"
LINUX_PID_PATH = "/tmp/cursor-self-hosted/worker.pid"
LINUX_WORKER_LOG_PATH = "/tmp/cursor-self-hosted/worker.log"
DEFAULT_REPO_URL = "https://github.com/daytona/guides"
DEFAULT_REPO_REF = "main"
WINDOWS_GIT_PATH = r"C:\Program Files\Git\cmd\git.exe"
POLL_SECONDS = 3.0
# Cursor checks repository access with GitHub before it answers this call.
# Retrying it could create duplicate agents, so allow a slow answer instead.
AGENT_CREATE_TIMEOUT_SECONDS = 120.0


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
            "--target eu-central-1 --snapshot cursor-self-hosted-linux-vm-abcd1234"
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
        "--cursor-mode",
        choices=("machine", "team-pool"),
        default="machine",
        help=(
            "personal My Machines worker or Enterprise team pool "
            "(default: machine)"
        ),
    )
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
            / ".venv/bin/spawn-cursor-self-hosted-worker"
        ),
        help="spawn-cursor-self-hosted-worker path",
    )
    result.add_argument(
        "--any-repo",
        action="store_true",
        help=(
            "team-pool only: omit repos from the Cursor request so the pool "
            "serves it as an any-repo request"
        ),
    )
    result.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help=f"HTTPS GitHub repository for the request (default: {DEFAULT_REPO_URL})",
    )
    result.add_argument(
        "--repo-ref",
        default=DEFAULT_REPO_REF,
        help=f"branch or commit to start from (default: {DEFAULT_REPO_REF})",
    )
    result.add_argument(
        "--keep-sandbox-on-failure",
        action="store_true",
        help=(
            "leave the worker sandbox running when the run fails so it can be "
            "inspected; the sandbox id is printed to stderr"
        ),
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
    *,
    timeout: float = 30,
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(
            f"Cursor {method} {path} returned HTTP {error.code}: {detail}"
        ) from error
    if not content:
        return {}
    return json.loads(content)


def cancel_cursor_run(api_key: str, agent_id: str, run_id: str) -> None:
    try:
        cursor_request(
            api_key,
            "POST",
            f"/v1/agents/{urllib.parse.quote(agent_id)}/runs/"
            f"{urllib.parse.quote(run_id)}/cancel",
        )
    except RuntimeError as error:
        if "run_not_cancellable" in str(error):
            return
        raise


def cursor_run_conversation(api_key: str, agent_id: str, run_id: str) -> str:
    """Return the agent conversation as compact text; never raise."""
    try:
        payload = cursor_request(
            api_key,
            "GET",
            f"/v0/agents/{urllib.parse.quote(agent_id)}/conversation",
        )
    except Exception as error:  # diagnostics only
        return f"<unavailable: {error}>"
    if not isinstance(payload, dict):
        return json.dumps(payload)[-3000:]
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return json.dumps(payload, sort_keys=True)[-3000:]
    lines = [
        f"{message.get('type', '?')}: {str(message.get('text', ''))[:600]}"
        for message in messages
        if isinstance(message, dict)
    ]
    return f"run {run_id}: " + " | ".join(lines)[-3000:]


def _error_status_codes(error: BaseException) -> set[int]:
    codes: set[int] = set()
    current: BaseException | None = error
    while current is not None:
        for status_code in (
            getattr(current, "status_code", None),
            getattr(getattr(current, "response", None), "status_code", None),
        ):
            try:
                if status_code is not None:
                    codes.add(int(status_code))
            except (TypeError, ValueError):
                pass
        for match in re.finditer(r"(?:HTTP |error ')(\d{3})\b", str(current)):
            codes.add(int(match.group(1)))
        current = current.__cause__ or current.__context__
    return codes


def is_not_found(error: BaseException) -> bool:
    return 404 in _error_status_codes(error)


def is_guest_unreachable(error: BaseException) -> bool:
    """The Daytona toolbox proxy answers 502-504 until a VM guest finishes booting."""
    return bool({502, 503, 504} & _error_status_codes(error))


def decode_text(content: object) -> str:
    if isinstance(content, bytes):
        if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return content.decode("utf-16", errors="replace")
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def find_sandbox(daytona: Daytona, route_name: str) -> Any | None:
    sandboxes = list(
        daytona.list(
            ListSandboxesQuery(labels={"cursor.pool": route_name})
        )
    )
    if not sandboxes:
        return None
    if len(sandboxes) != 1:
        names = sorted(str(item.name) for item in sandboxes)
        raise RuntimeError(f"Pool {route_name} has multiple sandboxes: {names}")
    return sandboxes[0]


def marker_path(sandbox_class: str) -> str:
    return WINDOWS_MARKER_PATH if sandbox_class == "windows" else LINUX_MARKER_PATH


def read_marker(
    sandbox: Any,
    sandbox_class: str,
    *,
    guest_may_be_booting: bool = False,
) -> str | None:
    path = marker_path(sandbox_class)
    if sandbox_class == "windows":
        path = path.replace("\\", "/")
    try:
        return decode_text(sandbox.fs.download_file(path)).strip()
    except Exception as error:
        if is_not_found(error) or isinstance(error, FileNotFoundError):
            return None
        if guest_may_be_booting and is_guest_unreachable(error):
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


def cleanup_with_retries(
    description: str,
    action: Callable[[], object],
    failures: list[str],
    secrets_to_redact: tuple[str, ...],
) -> None:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            action()
            return
        except Exception as error:
            if is_not_found(error):
                return
            last_error = error
            if attempt < 2:
                time.sleep(POLL_SECONDS)
    message = f"{description}: {last_error}"
    for secret_value in secrets_to_redact:
        message = message.replace(secret_value, "<redacted>")
    failures.append(message)


def delete_sandbox_and_wait(daytona: Daytona, sandbox: Any) -> None:
    sandbox_id = str(sandbox.id)
    try:
        daytona.delete(sandbox, timeout=300)
    except Exception as error:
        if is_not_found(error):
            return
        raise
    wait_for_deletion(
        daytona,
        sandbox_id,
        time.monotonic() + 60,
    )


def machine_worker_command(
    config: Config,
    route_name: str,
    sandbox_class: str,
) -> list[str]:
    if sandbox_class == "windows":
        command = [WINDOWS_AGENT_INDEX_PATH, "worker"]
        worker_directory = WINDOWS_WORKSPACE_PATH
    else:
        command = ["/usr/local/bin/agent", "worker"]
        worker_directory = "/home/daytona/workspace"
    command.extend(
        (
            "--worker-dir",
            worker_directory,
            "--management-addr",
            "0.0.0.0:8080",
            "--name",
            route_name,
            "--idle-release-timeout",
            str(config.idle_release_timeout_seconds),
            "start",
        )
    )
    return command


def linux_machine_launch_command(command: list[str]) -> str:
    worker = shlex.join(command)
    pid_path = shlex.quote(LINUX_PID_PATH)
    log_path = shlex.quote(LINUX_WORKER_LOG_PATH)
    inner = " && ".join(
        (
            "mkdir -p /tmp/cursor-self-hosted",
            f"rm -f {pid_path}",
            f"(nohup {worker} > {log_path} 2>&1 < /dev/null & echo $! > {pid_path})",
            "sleep 1",
            f"pid=$(cat {pid_path})",
            'case "$pid" in ""|*[!0-9]*) exit 1;; esac',
            'test "$pid" -gt 0',
            'kill -0 "$pid" 2>/dev/null',
            'printf \'%s\n\' "$pid"',
        )
    )
    return f"sh -c {shlex.quote(inner)}"


def worker_diagnostics(
    sandbox: Any,
    sandbox_class: str,
    secrets_to_redact: tuple[str, ...],
) -> str:
    paths = (
        (WINDOWS_WORKER_STDERR_PATH, WINDOWS_WORKER_STDOUT_PATH)
        if sandbox_class == "windows"
        else (LINUX_WORKER_LOG_PATH,)
    )
    tails: list[str] = []
    for path in paths:
        if sandbox_class == "windows":
            path = path.replace("\\", "/")
        try:
            candidate = decode_text(sandbox.fs.download_file(path))
        except Exception:
            continue
        if candidate.strip():
            tails.append(f"--- {path} ---\n{candidate[-4000:]}")
    output = "\n".join(tails) or "worker produced no readable log"
    for secret_value in secrets_to_redact:
        output = output.replace(secret_value, "<redacted>")
    return output


def cloned_repository_origins(sandbox: Any, sandbox_class: str) -> list[str]:
    """Return credential-free origin URLs of checked-out repositories.

    Only repositories with a resolvable HEAD count: the spawn command seeds
    `origin` before the worker starts, so an origin alone does not prove that
    the sessionStart hook fetched and checked out the requested ref.
    """
    if sandbox_class == "windows":
        script = (
            "$ProgressPreference = 'SilentlyContinue'; "
            f"$roots = @(Get-Item -LiteralPath '{WINDOWS_WORKSPACE_PATH}') + "
            f"@(Get-ChildItem -LiteralPath '{WINDOWS_WORKSPACE_PATH}' -Directory); "
            "foreach ($root in $roots) { "
            f"& '{WINDOWS_GIT_PATH}' -C $root.FullName rev-parse --verify --quiet HEAD *> $null; "
            "if ($LASTEXITCODE -eq 0) { "
            f"& '{WINDOWS_GIT_PATH}' -C $root.FullName remote get-url origin }} }}; "
            "exit 0"
        )
        response = sandbox.process.exec(powershell_encoded(script), timeout=60)
    else:
        listing = (
            "for d in /home/daytona/workspace /home/daytona/workspace/*/; do "
            'git -C "$d" rev-parse --verify --quiet HEAD >/dev/null 2>&1 '
            '&& git -C "$d" remote get-url origin; done; true'
        )
        response = sandbox.process.exec(f"sh -c {shlex.quote(listing)}", timeout=60)
    if getattr(response, "exit_code", 1) != 0:
        detail = str(getattr(response, "result", ""))[-2000:]
        raise RuntimeError(f"Failed to list cloned repositories: {detail}")
    return sorted(
        strip_url_credentials(line.strip())
        for line in decode_text(getattr(response, "result", "")).splitlines()
        if line.strip()
    )


def strip_url_credentials(url: str) -> str:
    """Drop userinfo and a trailing .git so origin URLs compare to request URLs."""
    parts = urllib.parse.urlsplit(url)
    if parts.hostname:
        netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
        url = urllib.parse.urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
    return url.removesuffix(".git").rstrip("/")


def prepare_machine_workspace(
    sandbox: Any,
    sandbox_class: str,
    *,
    repo_url: str,
    repo_ref: str,
) -> None:
    if sandbox_class == "windows":
        script = (
            "$ErrorActionPreference = 'Stop'; "
            f"Set-Location -LiteralPath '{WINDOWS_WORKSPACE_PATH}'; "
            f"& '{WINDOWS_GIT_PATH}' clone --depth 1 --branch "
            f"'{repo_ref}' '{repo_url}' .; "
            "if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }; "
            "Add-Content -LiteralPath '.git\\info\\exclude' "
            "-Value '.cursor-self-hosted-live-marker.txt'"
        )
        response = sandbox.process.exec(powershell_encoded(script), timeout=180)
    else:
        clone = shlex.join(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                repo_ref,
                repo_url,
                ".",
            ]
        )
        exclude_command = (
            f"printf '%s\\n' {shlex.quote('.cursor-self-hosted-live-marker.txt')} "
            ">> .git/info/exclude"
        )
        response = sandbox.process.exec(
            f"sh -c {shlex.quote(f'{clone} && {exclude_command}')}",
            cwd="/home/daytona/workspace",
            timeout=180,
        )
    if getattr(response, "exit_code", 1) != 0:
        detail = str(getattr(response, "result", ""))[-2000:]
        raise RuntimeError(f"Failed to prepare the machine workspace: {detail}")


def start_machine_worker_process(
    sandbox: Any,
    config: Config,
    route_name: str,
    sandbox_class: str,
) -> str:
    command = machine_worker_command(config, route_name, sandbox_class)
    if sandbox_class == "windows":
        launch_config = {
            "environment": worker_environment(config),
            "arguments": subprocess.list2cmdline(command),
        }
        sandbox.fs.upload_file(
            json.dumps(launch_config, sort_keys=True).encode("utf-8"),
            WINDOWS_LAUNCH_CONFIG_PATH,
        )
        try:
            response = sandbox.process.exec(
                _bootstrap_launcher(),
                timeout=config.sandbox_launch_timeout_seconds,
            )
        except Exception:
            response = None
        if response is not None and getattr(response, "exit_code", 1) != 0:
            raise RuntimeError("Windows machine worker bootstrap failed")
        pid: str | None = None
    else:
        response = sandbox.process.exec(
            linux_machine_launch_command(command),
            cwd="/home/daytona/workspace",
            env=worker_environment(config),
            timeout=config.sandbox_launch_timeout_seconds,
        )
        if getattr(response, "exit_code", 1) != 0:
            raise RuntimeError("Linux machine worker failed to launch")
        pid = _parse_worker_pid(getattr(response, "result", ""))

    deadline = time.monotonic() + config.sandbox_launch_timeout_seconds
    while time.monotonic() < deadline:
        if pid is None:
            try:
                pid = read_pid(sandbox, sandbox_class)
            except Exception as error:
                if not (is_not_found(error) or isinstance(error, FileNotFoundError)):
                    raise
        if pid is not None:
            try:
                if worker_is_live(sandbox, sandbox_class, pid):
                    return pid
            except Exception:
                pass
        time.sleep(1)
    diagnostics = worker_diagnostics(
        sandbox,
        sandbox_class,
        (config.daytona_api_key, config.cursor_api_key),
    )
    raise RuntimeError(f"Machine worker exited during startup: {diagnostics}")


def start_direct_worker(
    daytona: Daytona,
    *,
    daytona_key: str,
    cursor_key: str,
    route_name: str,
    sandbox_class: str,
    snapshot: str,
    target: str,
    repo_url: str,
    repo_ref: str,
) -> tuple[Any, Config]:
    config = Config(
        daytona_api_key=daytona_key,
        daytona_target=target,
        snapshot_name=snapshot,
        cursor_api_key=cursor_key,
        cursor_agent_worker_id="",
        cursor_pool=route_name,
        cursor_request_id="",
        cursor_repo_url=None,
        cursor_repo_urls=(),
        cursor_worker_name=route_name,
        cursor_api_url=None,
        cursor_api_endpoint=None,
        idle_release_timeout_seconds=600,
        monitor_poll_seconds=2.0,
        sandbox_create_timeout_seconds=300,
        sandbox_launch_timeout_seconds=180,
    )
    sandbox = daytona.create(
        CreateSandboxFromSnapshotParams(
            name=f"cursor-live-{sandbox_class.replace('-', '')}-{secrets.token_hex(4)}",
            snapshot=snapshot,
            labels={
                "cursor.machine": route_name,
                "cursor.sandbox_class": sandbox_class,
                "cursor.live_e2e": "true",
            },
            auto_stop_interval=10,
            auto_delete_interval=0,
        ),
        timeout=300,
    )
    stage = "machine workspace preparation"
    try:
        prepare_machine_workspace(
            sandbox,
            sandbox_class,
            repo_url=repo_url,
            repo_ref=repo_ref,
        )
        stage = "machine worker launch"
        start_machine_worker_process(
            sandbox,
            config,
            route_name,
            sandbox_class,
        )
    except Exception as error:
        diagnostics = worker_diagnostics(
            sandbox,
            sandbox_class,
            (daytona_key, cursor_key),
        )
        cleanup_failures: list[str] = []
        cleanup_with_retries(
            "Daytona sandbox cleanup",
            lambda: delete_sandbox_and_wait(daytona, sandbox),
            cleanup_failures,
            (daytona_key, cursor_key),
        )
        cleanup_detail = (
            f"; {'; '.join(cleanup_failures)}" if cleanup_failures else ""
        )
        raise RuntimeError(
            f"{stage} failed: {error}; {diagnostics}{cleanup_detail}"
        ) from error
    return sandbox, config


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.cursor_mode == "team-pool":
        if not args.agent or not Path(args.agent).is_file():
            parser().error("--agent must name the Cursor Agent executable")
        if not Path(args.spawn).is_file():
            parser().error("--spawn must name spawn-cursor-self-hosted-worker")
    elif args.any_repo:
        parser().error("--any-repo requires --cursor-mode team-pool")

    daytona_key = required_secret("DAYTONA_API_KEY")
    cursor_key = required_secret("CURSOR_API_KEY")
    token = secrets.token_hex(16)
    route_name = f"daytona-{args.sandbox_class.replace('-', '')}-{token[:8]}"
    agent_id: str | None = None
    run_id: str | None = None
    sandbox: Any | None = None
    machine_config: Config | None = None
    controller: subprocess.Popen[str] | None = None
    run_payload: dict[str, Any] | None = None
    cleanup_failures: list[str] = []
    result_payload: dict[str, object] | None = None
    exit_status = 1
    deadline = time.monotonic() + args.timeout

    with tempfile.TemporaryDirectory(prefix="cursor-self-hosted-live-") as temp_dir:
        stdout_path = Path(temp_dir, "controller.stdout.log")
        stderr_path = Path(temp_dir, "controller.stderr.log")
        stdout_file = stdout_path.open("w")
        stderr_file = stderr_path.open("w")
        daytona = Daytona(
            DaytonaConfig(api_key=daytona_key, target=args.target)
        )
        try:
            if args.cursor_mode == "machine":
                sandbox, machine_config = start_direct_worker(
                    daytona,
                    daytona_key=daytona_key,
                    cursor_key=cursor_key,
                    route_name=route_name,
                    sandbox_class=args.sandbox_class,
                    snapshot=args.snapshot,
                    target=args.target,
                    repo_url=args.repo_url,
                    repo_ref=args.repo_ref,
                )
            else:
                cursor_request(
                    cursor_key,
                    "POST",
                    "/v0/private-workers/pools",
                    {"scope": "team", "poolName": route_name},
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
                        route_name,
                    ],
                    env=controller_env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    start_new_session=True,
                )
            agent_request: dict[str, Any] = {
                "name": f"Daytona {args.sandbox_class} live E2E",
                "prompt": {
                    "text": (
                        f"Create {marker_path(args.sandbox_class)} with the exact "
                        f"text {token} and no trailing newline. Read the file back. "
                        "Do not change any other file."
                    )
                },
                "env": {
                    "type": (
                        "machine"
                        if args.cursor_mode == "machine"
                        else "pool"
                    ),
                    "name": route_name,
                },
            }
            if not args.any_repo:
                agent_request["repos"] = [
                    {"url": args.repo_url, "startingRef": args.repo_ref}
                ]
            if args.cursor_mode == "machine":
                agent_request["workOnCurrentBranch"] = True
            route_deadline = min(deadline, time.monotonic() + 120)
            while True:
                try:
                    created = cursor_request(
                        cursor_key,
                        "POST",
                        "/v1/agents",
                        agent_request,
                        timeout=AGENT_CREATE_TIMEOUT_SECONDS,
                    )
                    break
                except RuntimeError as error:
                    route_is_starting = (
                        args.cursor_mode == "machine"
                        and "Repo-less private-worker requests require"
                        in str(error)
                    )
                    if not route_is_starting or time.monotonic() >= route_deadline:
                        raise
                    if sandbox is not None:
                        pid = read_pid(sandbox, args.sandbox_class)
                        if not worker_is_live(sandbox, args.sandbox_class, pid):
                            diagnostics = worker_diagnostics(
                                sandbox,
                                args.sandbox_class,
                                (daytona_key, cursor_key),
                            )
                            raise RuntimeError(
                                f"Machine worker exited before registration: {diagnostics}"
                            ) from error
                    time.sleep(POLL_SECONDS)
            if not isinstance(created, dict):
                raise RuntimeError("Cursor create-agent response is not an object")
            agent_id = str(created["agent"]["id"])
            run_id = str(created["run"]["id"])

            marker_value: str | None = None
            while time.monotonic() < deadline:
                if controller is not None and controller.poll() is not None:
                    raise RuntimeError(
                        f"Controller exited with status {controller.returncode}"
                    )
                try:
                    run = cursor_request(
                        cursor_key,
                        "GET",
                        f"/v1/agents/{urllib.parse.quote(agent_id)}/runs/"
                        f"{urllib.parse.quote(run_id)}",
                    )
                except (TimeoutError, urllib.error.URLError) as error:
                    # Cursor's API occasionally stalls a poll; the deadline bounds retries.
                    print(f"cursor poll retry: {error}", file=sys.stderr)
                    time.sleep(POLL_SECONDS)
                    continue
                if not isinstance(run, dict):
                    raise RuntimeError("Cursor run response is not an object")
                run_payload = run
                sandbox = sandbox or find_sandbox(daytona, route_name)
                if sandbox is not None:
                    marker_value = read_marker(
                        sandbox,
                        args.sandbox_class,
                        guest_may_be_booting=True,
                    )
                status = str(run.get("status", ""))
                if status in TERMINAL_RUN_STATES:
                    if status != "FINISHED":
                        detail = json.dumps(run, sort_keys=True)[-3000:]
                        conversation = cursor_run_conversation(
                            cursor_key, agent_id, run_id
                        )
                        raise RuntimeError(
                            f"Cursor run ended with {status}: {detail}\n"
                            f"conversation: {conversation}"
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
            cloned: list[str] = []
            if args.cursor_mode == "team-pool" and not args.any_repo:
                cloned = cloned_repository_origins(sandbox, args.sandbox_class)
                if strip_url_credentials(args.repo_url) not in cloned:
                    raise RuntimeError(
                        "The worker did not clone the requested repository "
                        f"{args.repo_url} into the workspace; found {cloned}"
                    )

            pid = read_pid(sandbox, args.sandbox_class)
            worker_check_deadline = min(deadline, time.monotonic() + 30)
            while time.monotonic() < worker_check_deadline:
                try:
                    if worker_is_live(sandbox, args.sandbox_class, pid):
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError(f"Worker PID {pid} is not live after the run")
            if machine_config is not None:
                start_monitor(
                    machine_config,
                    str(sandbox.id),
                    pid,
                    args.sandbox_class,
                )
            sandbox_id = str(sandbox.id)
            stop_worker(sandbox, args.sandbox_class, pid)
            wait_for_deletion(
                daytona,
                sandbox_id,
                min(deadline, time.monotonic() + 180),
            )
            sandbox = None

            result_payload = {
                "agent_id": agent_id,
                "cloned_repositories": cloned,
                "cursor_mode": args.cursor_mode,
                "repo_url": None if args.any_repo else args.repo_url,
                "route_name": route_name,
                "run_id": run_id,
                "run_status": run_payload["status"] if run_payload else None,
                "sandbox_class": args.sandbox_class,
                "snapshot_name": args.snapshot,
                "target": args.target,
                "worker_cleanup": "deleted",
            }
            exit_status = 0
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
            if sandbox is not None:
                diagnostics = worker_diagnostics(
                    sandbox,
                    args.sandbox_class,
                    (daytona_key, cursor_key),
                )
                if diagnostics.strip():
                    print(diagnostics, file=sys.stderr)
            exit_status = 1
        finally:
            terminate_process(controller)
            if sandbox is not None and exit_status != 0 and args.keep_sandbox_on_failure:
                print(
                    f"kept sandbox {sandbox.id} for inspection; delete it manually",
                    file=sys.stderr,
                )
            elif sandbox is not None:
                cleanup_with_retries(
                    "Daytona sandbox cleanup",
                    lambda: delete_sandbox_and_wait(daytona, sandbox),
                    cleanup_failures,
                    (daytona_key, cursor_key),
                )
            if agent_id is not None and run_id is not None:
                cleanup_with_retries(
                    "Cursor run cancellation",
                    lambda: cancel_cursor_run(
                        cursor_key,
                        agent_id,
                        run_id,
                    ),
                    cleanup_failures,
                    (daytona_key, cursor_key),
                )
            if agent_id is not None:
                cleanup_with_retries(
                    "Cursor agent deletion",
                    lambda: cursor_request(
                        cursor_key,
                        "DELETE",
                        f"/v1/agents/{urllib.parse.quote(agent_id)}",
                    ),
                    cleanup_failures,
                    (daytona_key, cursor_key),
                )
            if args.cursor_mode == "team-pool":
                # A pool whose worker advertised a repository is recorded as
                # repo-backed and only deregisters with the repo identity.
                pool_identity = {"scope": "team", "pool_name": route_name}
                if not args.any_repo:
                    owner, name = strip_url_credentials(args.repo_url).rsplit("/", 2)[-2:]
                    pool_identity.update(repo_owner=owner, repo_name=name)
                query = urllib.parse.urlencode(pool_identity)
                cleanup_with_retries(
                    "Cursor pool deletion",
                    lambda: cursor_request(
                        cursor_key,
                        "DELETE",
                        f"/v0/private-workers/pools?{query}",
                    ),
                    cleanup_failures,
                    (daytona_key, cursor_key),
                )
            stdout_file.close()
            stderr_file.close()
        if cleanup_failures:
            exit_status = 1
            for cleanup_failure in cleanup_failures:
                print(f"cleanup failed: {cleanup_failure}", file=sys.stderr)
        if result_payload is not None and exit_status == 0:
            print(json.dumps(result_payload, sort_keys=True))
        return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
