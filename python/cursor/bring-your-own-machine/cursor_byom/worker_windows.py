"""Start and inspect the Cursor worker in a Daytona Windows sandbox."""

from __future__ import annotations

import base64
import json
import subprocess
import time
from collections.abc import Callable, Iterable
from typing import Any

from .config import Config, redact, worker_environment

WINDOWS_POWERSHELL_PATH = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)
WINDOWS_AGENT_VERSION = "2026.08.25-3e8eec8"
WINDOWS_AGENT_ROOT = (
    rf"C:\ProgramData\cursor-agent\versions\{WINDOWS_AGENT_VERSION}"
)
WINDOWS_AGENT_NODE_PATH = rf"{WINDOWS_AGENT_ROOT}\node.exe"
WINDOWS_AGENT_INDEX_PATH = rf"{WINDOWS_AGENT_ROOT}\index.js"
WINDOWS_WORKSPACE_PATH = r"C:\cursor\workspace"
WINDOWS_RUNTIME_ROOT = r"C:\ProgramData\cursor-byom"
WINDOWS_CLONE_HOOK_PATH = (
    rf"{WINDOWS_RUNTIME_ROOT}\clone-cursor-byom-repos.cmd"
)
WINDOWS_BOOTSTRAP_PATH = rf"{WINDOWS_RUNTIME_ROOT}\windows-bootstrap.ps1"
WINDOWS_LAUNCH_CONFIG_PATH = rf"{WINDOWS_RUNTIME_ROOT}\launch.json"
WINDOWS_WORKER_PID_PATH = rf"{WINDOWS_RUNTIME_ROOT}\worker.pid"
WINDOWS_WORKER_STDIN_PATH = rf"{WINDOWS_RUNTIME_ROOT}\worker.stdin"
WINDOWS_WORKER_STDOUT_PATH = rf"{WINDOWS_RUNTIME_ROOT}\worker.stdout.log"
WINDOWS_WORKER_STDERR_PATH = rf"{WINDOWS_RUNTIME_ROOT}\worker.stderr.log"
WINDOWS_BOOTSTRAP_STDIN_PATH = rf"{WINDOWS_RUNTIME_ROOT}\bootstrap.stdin"
WINDOWS_BOOTSTRAP_STDOUT_PATH = (
    rf"{WINDOWS_RUNTIME_ROOT}\bootstrap.stdout.log"
)
WINDOWS_BOOTSTRAP_STDERR_PATH = (
    rf"{WINDOWS_RUNTIME_ROOT}\bootstrap.stderr.log"
)
WINDOWS_PID_POLL_SECONDS = 1.0


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell_encoded(script: str) -> str:
    """Wrap a script in the encoding required by Daytona Windows exec."""

    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return (
        f"{WINDOWS_POWERSHELL_PATH} -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -EncodedCommand {encoded}"
    )


def _worker_arguments(config: Config) -> str:
    arguments = [
        WINDOWS_AGENT_INDEX_PATH,
        "worker",
        "--pool",
        config.cursor_pool,
        "--worker-dir",
        WINDOWS_WORKSPACE_PATH,
        "--management-addr",
        "0.0.0.0:8080",
    ]
    if config.cursor_repo_urls:
        arguments.extend(
            (
                "--mint-github-token",
                "--on-session-start",
                WINDOWS_CLONE_HOOK_PATH,
            )
        )
    arguments.extend(
        (
            "--idle-release-timeout",
            str(config.idle_release_timeout_seconds),
            "start",
        )
    )
    return subprocess.list2cmdline(arguments)


def _bootstrap_launcher() -> str:
    bootstrap_arguments = ", ".join(
        _powershell_quote(value)
        for value in (
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            WINDOWS_BOOTSTRAP_PATH,
            "-ConfigPath",
            WINDOWS_LAUNCH_CONFIG_PATH,
            "-Executable",
            WINDOWS_AGENT_NODE_PATH,
            "-WorkingDirectory",
            WINDOWS_WORKSPACE_PATH,
            "-PidPath",
            WINDOWS_WORKER_PID_PATH,
            "-StdinPath",
            WINDOWS_WORKER_STDIN_PATH,
            "-StdoutPath",
            WINDOWS_WORKER_STDOUT_PATH,
            "-StderrPath",
            WINDOWS_WORKER_STDERR_PATH,
        )
    )
    return powershell_encoded(
        f"Remove-Item -LiteralPath {_powershell_quote(WINDOWS_WORKER_PID_PATH)} "
        "-Force -ErrorAction SilentlyContinue; "
        "Set-Content -LiteralPath "
        f"{_powershell_quote(WINDOWS_BOOTSTRAP_STDIN_PATH)} "
        "-Value '' -Encoding Ascii; "
        f"Start-Process -FilePath {_powershell_quote(WINDOWS_POWERSHELL_PATH)} "
        f"-ArgumentList @({bootstrap_arguments}) -WindowStyle Hidden "
        "-RedirectStandardInput "
        f"{_powershell_quote(WINDOWS_BOOTSTRAP_STDIN_PATH)} "
        "-RedirectStandardOutput "
        f"{_powershell_quote(WINDOWS_BOOTSTRAP_STDOUT_PATH)} "
        "-RedirectStandardError "
        f"{_powershell_quote(WINDOWS_BOOTSTRAP_STDERR_PATH)}"
    )


def _decode_windows_text(content: object) -> str:
    if not isinstance(content, bytes):
        return str(content or "")
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16", errors="replace")
    if b"\x00" in content:
        return content.decode("utf-16le", errors="replace")
    return content.decode("utf-8", errors="replace")


def _download_text(sandbox: Any, path: str) -> str:
    try:
        content = sandbox.fs.download_file(path.replace("\\", "/"))
    except Exception:
        return ""
    return _decode_windows_text(content)


def _parse_positive_pid(value: str) -> str | None:
    pid = value.strip()
    if not pid.isdigit() or int(pid) <= 0:
        return None
    return pid


def _known_secrets(config: Config) -> Iterable[str]:
    environment = worker_environment(config)
    daytona_api_key = getattr(config, "daytona_api_key", None)
    if daytona_api_key:
        yield str(daytona_api_key)
    yield from environment.values()


def _bootstrap_diagnostics(sandbox: Any, config: Config) -> str:
    output = (
        _download_text(sandbox, WINDOWS_BOOTSTRAP_STDERR_PATH).strip()
        or _download_text(sandbox, WINDOWS_BOOTSTRAP_STDOUT_PATH).strip()
        or "bootstrap produced no output"
    )
    return redact(output, _known_secrets(config))[-4000:]


def _remove_launch_config(sandbox: Any, timeout: int) -> None:
    cleanup = powershell_encoded(
        f"Remove-Item -LiteralPath {_powershell_quote(WINDOWS_LAUNCH_CONFIG_PATH)} "
        "-Force -ErrorAction SilentlyContinue"
    )
    try:
        sandbox.process.exec(cleanup, timeout=timeout)
    except Exception:
        pass


def start_windows_worker_process(
    sandbox: Any,
    config: Config,
    *,
    sleep: Callable[[float], object] = time.sleep,
) -> str:
    """Start the baked Cursor worker and return its positive process ID."""

    launch_config = {
        "environment": worker_environment(config),
        "arguments": _worker_arguments(config),
    }
    try:
        sandbox.fs.upload_file(
            json.dumps(launch_config, sort_keys=True).encode("utf-8"),
            WINDOWS_LAUNCH_CONFIG_PATH,
        )
    except Exception:
        _remove_launch_config(
            sandbox,
            min(30, config.sandbox_launch_timeout_seconds),
        )
        raise RuntimeError(
            "Failed to upload the Windows worker launch configuration"
        ) from None

    try:
        response = sandbox.process.exec(
            _bootstrap_launcher(),
            timeout=config.sandbox_launch_timeout_seconds,
        )
    except Exception:
        response = None

    if response is not None and getattr(response, "exit_code", 1) != 0:
        diagnostics = _bootstrap_diagnostics(sandbox, config)
        _remove_launch_config(
            sandbox,
            min(30, config.sandbox_launch_timeout_seconds),
        )
        raise RuntimeError(f"Failed to start the Windows worker: {diagnostics}")

    remaining = float(config.sandbox_launch_timeout_seconds)
    while remaining > 0:
        delay = min(WINDOWS_PID_POLL_SECONDS, remaining)
        sleep(delay)
        remaining -= delay
        pid = _parse_positive_pid(
            _download_text(sandbox, WINDOWS_WORKER_PID_PATH)
        )
        if pid is not None:
            return pid

    diagnostics = _bootstrap_diagnostics(sandbox, config)
    _remove_launch_config(
        sandbox,
        min(30, config.sandbox_launch_timeout_seconds),
    )
    raise RuntimeError(
        f"Windows worker did not write a valid process ID: {diagnostics}"
    )


def windows_inspection_command(pid: str) -> str:
    """Return a command that reports whether PID is the baked Node worker."""

    validated_pid = _parse_positive_pid(str(pid))
    if validated_pid is None:
        raise ValueError("Windows worker process ID must be a positive integer")
    expected_path = _powershell_quote(WINDOWS_AGENT_NODE_PATH)
    return powershell_encoded(
        f"$process = Get-Process -Id {validated_pid} -ErrorAction SilentlyContinue; "
        "if ($null -eq $process) { Write-Output 'exited'; exit 0 }; "
        "$path = $null; "
        "try { $path = $process.Path } catch { }; "
        f"if ([string]::Equals($path, {expected_path}, "
        "[System.StringComparison]::OrdinalIgnoreCase)) "
        "{ Write-Output 'running' } else { Write-Output 'exited' }"
    )
