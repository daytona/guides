"""Launch the Devin remote while accommodating Windows sandbox constraints.

The exec API adds an outer PowerShell layer, so scripts use Base64
``EncodedCommand``. Synchronous execs are killed after roughly 40 seconds, so
the bootstrap detaches and its pid file is authoritative. First launch absorbs
a Defender scan. Because filesystem transfers mishandle backslashes and large
payloads, paths use forward slashes where required and downloads run in-sandbox
through ``curl.exe``.
"""

from __future__ import annotations

import base64
import importlib.resources as resources
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Mapping

from .config import Config
from .queue import QueueEntry
from .sandbox import safe_identifier, sandbox_name_for

if TYPE_CHECKING:
    from .worker import WorkerHandle

WINDOWS_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
WINDOWS_CURL = r"C:\Windows\System32\curl.exe"
WINDOWS_REMOTE_CACHE_DIR = r"C:\ProgramData\devin-outposts\remote"
WINDOWS_SESSION_ROOT = r"C:\ProgramData\devin-outposts\sessions"
WINDOWS_BOOTSTRAP_SCRIPT = (
    resources.files(__package__)
    .joinpath("windows_bootstrap.ps1")
    .read_text(encoding="utf-8")
)
LOGGER = logging.getLogger(__name__)


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell_encoded(script: str) -> str:
    """Wrap a script for process.exec on Windows sandboxes.

    The exec API routes commands through an outer PowerShell layer that
    interpolates inside embedded double quotes; -EncodedCommand bypasses it.
    """
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return (
        f"{WINDOWS_POWERSHELL} -NoLogo -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -EncodedCommand {encoded}"
    )


def windows_remote_filename(remote_sha: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", remote_sha):
        raise ValueError("remote SHA must be hexadecimal")
    return f"devin-remote_{remote_sha}_windows_x64.exe"


def windows_download_script(*, remote_sha: str, checksum: str, executable: str) -> str:
    """In-sandbox verified download of the pinned Windows remote.

    Uploading the binary from the host fails: large fs.upload_file payloads
    return HTTP 502. The sandbox downloads the published artifact itself and
    verifies the host-fetched SHA-256 before the binary is trusted. The
    trailing --help run absorbs the Defender scan of the fresh binary, which
    would otherwise block the detached launch.
    """
    filename = windows_remote_filename(remote_sha)
    from .worker import REMOTE_BASE_URL, parse_sha256

    digest = parse_sha256(checksum)
    return (
        f"$destination = {ps_quote(executable)}; "
        f"& {ps_quote(WINDOWS_CURL)} --fail --silent --show-error --location "
        f"--retry 3 --output $destination {ps_quote(f'{REMOTE_BASE_URL}/{filename}')}; "
        "if ($LASTEXITCODE -ne 0) { Write-Output ('DOWNLOAD_FAILED exit=' + $LASTEXITCODE); exit 1 }; "
        "$actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant(); "
        f"if ($actual -cne {ps_quote(digest)}) "
        "{ Write-Output ('CHECKSUM_MISMATCH actual=' + $actual); exit 1 }; "
        "& $destination --help | Out-Null; "
        "if ($LASTEXITCODE -ne 0) { Write-Output ('REMOTE_VERIFICATION_FAILED exit=' + $LASTEXITCODE); exit 1 }; "
        "Write-Output 'REMOTE_VERIFIED'"
    )


def windows_remote_environment(
    *,
    session_id: str,
    gateway_url: str,
    connect_token: str,
    state_dir: str,
    chrome_path: str,
) -> dict[str, str]:
    system_root = r"C:\Windows"
    system_profile = rf"{system_root}\System32\config\systemprofile"
    path = ";".join(
        (
            r"C:\ProgramData\devin-outposts\devin\bin",
            r"C:\Program Files\Git\cmd",
            r"C:\Program Files\Git\bin",
            r"C:\Program Files\ffmpeg\bin",
            rf"{system_root}\System32",
            system_root,
            rf"{system_root}\System32\WindowsPowerShell\v1.0",
        )
    )
    return {
        "DEVIN_OUTPOST_GATEWAY_URL": gateway_url,
        "DEVIN_OUTPOST_CONNECT_TOKEN": connect_token,
        "DEVIN_OUTPOST_SESSION_ID": session_id,
        "DEVIN_REMOTE_STATE_DIR": state_dir,
        "DEVIN_CHROME_PATH": chrome_path,
        "DEVIN_OUTPOST_DESKTOP": "true",
        "PATH": path,
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "ComSpec": rf"{system_root}\System32\cmd.exe",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "SystemDrive": "C:",
        "ALLUSERSPROFILE": r"C:\ProgramData",
        "ProgramFiles": r"C:\Program Files",
        "ProgramW6432": r"C:\Program Files",
        "ProgramFiles(x86)": r"C:\Program Files (x86)",
        "ProgramData": r"C:\ProgramData",
        "HOME": system_profile,
        "USERPROFILE": system_profile,
        "LOCALAPPDATA": rf"{system_profile}\AppData\Local",
        "APPDATA": rf"{system_profile}\AppData\Roaming",
        "TEMP": rf"{system_root}\Temp",
        "TMP": rf"{system_root}\Temp",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }


def windows_session_root(session_id: str) -> str:
    return rf"{WINDOWS_SESSION_ROOT}\{safe_identifier(session_id)}"


def windows_worker_paths(session_id: str) -> tuple[str, str]:
    root = windows_session_root(session_id)
    return rf"{root}\worker.pid", rf"{root}\worker.out.log"


def download_windows_text(sandbox: Any, path: str) -> str:
    """Read a small text file from a Windows sandbox.

    fs.download_file rejects backslash paths on Windows sandboxes, and
    PowerShell stream redirection writes UTF-16LE with a BOM.
    """
    normalized_path = path.replace("\\", "/")
    try:
        content = sandbox.fs.download_file(normalized_path)
    except Exception as exc:
        LOGGER.warning(
            "Unable to read Windows sandbox text file %r; treating it as empty (exception=%s)",
            normalized_path,
            type(exc).__name__,
        )
        return ""
    if isinstance(content, bytes):
        if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return content.decode("utf-16", errors="replace")
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def start_windows_worker_process(
    sandbox: Any,
    config: Config,
    session_id: str,
    entry: Any,
    claim: QueueEntry | Mapping[str, Any],
) -> WorkerHandle:
    from .worker import (
        WorkerHandle,
        _claim_connection,
        fetch_remote_checksum,
        parse_pid,
    )

    sandbox_name = sandbox_name_for(session_id)
    remote_sha, gateway_url, connect_token = _claim_connection(entry, claim)

    session_root = windows_session_root(session_id)
    remote_dir = rf"{WINDOWS_REMOTE_CACHE_DIR}\{remote_sha}"
    executable = rf"{remote_dir}\devin-remote.exe"
    bootstrap = rf"{session_root}\bootstrap.ps1"
    launch_config = rf"{session_root}\launch.json"
    pid_path, stdout_path = windows_worker_paths(session_id)
    stderr_path = rf"{session_root}\worker.err.log"
    bootstrap_out = rf"{session_root}\bootstrap.out.log"
    bootstrap_err = rf"{session_root}\bootstrap.err.log"
    state_dir = rf"{session_root}\state"

    mkdir = powershell_encoded(
        "; ".join(
            f"New-Item -ItemType Directory -Path {ps_quote(path)} -Force | Out-Null"
            for path in (session_root, remote_dir, state_dir, config.windows_workdir)
        )
    )
    response = sandbox.process.exec(mkdir, timeout=30)
    if getattr(response, "exit_code", 1) != 0:
        raise RuntimeError(
            f"failed to prepare Windows worker directories: {response.result}"
        )

    checksum = fetch_remote_checksum(windows_remote_filename(remote_sha))
    download = windows_download_script(
        remote_sha=remote_sha, checksum=checksum, executable=executable
    )
    response = sandbox.process.exec(powershell_encoded(download), timeout=300)
    output = str(getattr(response, "result", "") or "")
    if getattr(response, "exit_code", 1) != 0 or "REMOTE_VERIFIED" not in output:
        raise RuntimeError(
            f"in-sandbox Windows remote download failed: {output.strip()}"
        )

    sandbox.fs.upload_file(WINDOWS_BOOTSTRAP_SCRIPT.encode(), bootstrap)
    environment = windows_remote_environment(
        session_id=session_id,
        gateway_url=gateway_url,
        connect_token=connect_token,
        state_dir=state_dir,
        chrome_path=config.windows_chrome_path,
    )
    sandbox.fs.upload_file(
        json.dumps({"environment": environment}, sort_keys=True).encode(),
        launch_config,
    )

    bootstrap_args = ", ".join(
        ps_quote(value)
        for value in (
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            bootstrap,
            "-ConfigPath",
            launch_config,
            "-Executable",
            executable,
            "-WorkingDirectory",
            config.windows_workdir,
            "-PidPath",
            pid_path,
            "-StdoutPath",
            stdout_path,
            "-StderrPath",
            stderr_path,
        )
    )
    # Synchronous execs on Windows sandboxes are killed server-side after
    # roughly 40 seconds, so the bootstrap launches detached and the PID file
    # is the source of truth for the launch.
    launcher = powershell_encoded(
        f"Remove-Item -LiteralPath {ps_quote(pid_path)} -Force -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath {ps_quote(WINDOWS_POWERSHELL)} "
        f"-ArgumentList @({bootstrap_args}) -WindowStyle Hidden "
        f"-RedirectStandardOutput {ps_quote(bootstrap_out)} "
        f"-RedirectStandardError {ps_quote(bootstrap_err)}"
    )
    try:
        response = sandbox.process.exec(launcher, timeout=30)
        if getattr(response, "exit_code", 1) != 0:
            raise RuntimeError(f"failed to start Windows remote: {response.result}")
    except RuntimeError:
        raise
    except Exception as exc:
        # A child that inherits the exec pipes keeps this call open until the
        # server kills it, even when the launch itself worked.
        LOGGER.info(
            "Windows launch exec unconfirmed for %s: %s",
            session_id,
            config.redacted(exc),
        )

    deadline = time.monotonic() + 180
    pid: str | None = None
    while not pid and time.monotonic() < deadline:
        time.sleep(3)
        pid = parse_pid(download_windows_text(sandbox, pid_path))
    if not pid:
        diagnostics = (
            download_windows_text(sandbox, bootstrap_err).strip()
            or download_windows_text(sandbox, bootstrap_out).strip()
            or "bootstrap produced no output"
        )
        raise RuntimeError(f"Windows remote did not write a process id: {diagnostics}")
    return WorkerHandle(
        sandbox_name=sandbox_name,
        pid=pid,
        pid_path=pid_path,
        log_path=stdout_path,
        platform="windows",
    )
