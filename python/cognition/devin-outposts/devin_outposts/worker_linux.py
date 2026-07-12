"""Launch the pinned Devin remote in Linux sandboxes.

The remote is downloaded and checksum-verified inside the sandbox, with session
state stored below ``/home/daytona/.devin/remote``.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import TYPE_CHECKING, Any, Mapping

from .config import Config
from .queue import QueueEntry
from .sandbox import safe_identifier, sandbox_name_for

if TYPE_CHECKING:
    from .worker import WorkerHandle

LINUX_REMOTE_CACHE_DIR = "/home/daytona/.devin/remote/cache"
LINUX_REMOTE_STATE_ROOT = "/home/daytona/.devin/remote/sessions"


def linux_remote_filename(remote_sha: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", remote_sha):
        raise ValueError("remote SHA must be hexadecimal")
    return f"devin-remote_{remote_sha}_linux_x64"


def linux_remote_command(
    *,
    remote_sha: str,
    checksum: str,
    workdir: str,
    state_dir: str,
    pid_path: str,
    log_path: str,
) -> str:
    filename = linux_remote_filename(remote_sha)
    from .worker import REMOTE_BASE_URL, parse_sha256

    digest = parse_sha256(checksum)
    binary = f"{LINUX_REMOTE_CACHE_DIR}/{filename}"
    partial = f"{binary}.partial"
    url = f"{REMOTE_BASE_URL}/{filename}"

    def verified(path: str) -> str:
        return (
            f"printf '%s  %s\\n' {digest} {shlex.quote(path)} | sha256sum -c --status"
        )

    download = (
        f"{verified(binary)} 2>/dev/null || {{ "
        f"curl -fsSL {shlex.quote(url)} -o {shlex.quote(partial)} && "
        f"{verified(partial)} && mv {shlex.quote(partial)} {shlex.quote(binary)}; }}"
    )
    launch = (
        f"nohup {shlex.quote(binary)} serve > {shlex.quote(log_path)} 2>&1 < /dev/null"
    )
    directories = " ".join(
        shlex.quote(path)
        for path in (
            workdir,
            state_dir,
            LINUX_REMOTE_CACHE_DIR,
            posixpath.dirname(pid_path) or "/tmp",
        )
    )
    inner = " && ".join(
        (
            f"mkdir -p {directories}",
            download,
            f"chmod +x {shlex.quote(binary)}",
            f"cd {shlex.quote(workdir)}",
            f"({launch} & echo $! > {shlex.quote(pid_path)})",
            f"cat {shlex.quote(pid_path)}",
        )
    )
    return f"sh -lc {shlex.quote(inner)}"


def linux_remote_environment(
    *,
    session_id: str,
    gateway_url: str,
    connect_token: str,
    state_dir: str,
    chrome_path: str,
) -> dict[str, str]:
    return {
        "DEVIN_OUTPOST_GATEWAY_URL": gateway_url,
        "DEVIN_OUTPOST_CONNECT_TOKEN": connect_token,
        "DEVIN_OUTPOST_SESSION_ID": session_id,
        "DEVIN_REMOTE_STATE_DIR": state_dir,
        "DEVIN_CHROME_PATH": chrome_path,
        "DEVIN_OUTPOST_DESKTOP": "true",
        "PATH": "/home/daytona/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/home/daytona",
        "USER": "daytona",
        "LOGNAME": "daytona",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "DISPLAY": ":0",
        "XAUTHORITY": "/home/daytona/.Xauthority",
    }


def remote_state_dir(session_id: str) -> str:
    return f"{LINUX_REMOTE_STATE_ROOT}/{safe_identifier(session_id)}"


def worker_paths(session_id: str) -> tuple[str, str]:
    safe = safe_identifier(session_id)
    return f"/tmp/devin-outposts/{safe}.pid", f"/tmp/devin-outposts/{safe}.log"


def start_linux_worker_process(
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
    checksum = fetch_remote_checksum(linux_remote_filename(remote_sha))
    state_dir = remote_state_dir(session_id)
    pid_path, log_path = worker_paths(session_id)
    command = linux_remote_command(
        remote_sha=remote_sha,
        checksum=checksum,
        workdir=config.workdir,
        state_dir=state_dir,
        pid_path=pid_path,
        log_path=log_path,
    )
    environment = linux_remote_environment(
        session_id=session_id,
        gateway_url=gateway_url,
        connect_token=connect_token,
        state_dir=state_dir,
        chrome_path=config.devin_chrome_path,
    )
    response = sandbox.process.exec(command, env=environment, timeout=300)
    if getattr(response, "exit_code", 1) != 0:
        raise RuntimeError("failed to start devin-remote process")
    pid = parse_pid(getattr(response, "result", ""))
    if not pid:
        raise RuntimeError("remote start did not return a process id")
    return WorkerHandle(
        sandbox_name=sandbox_name, pid=pid, pid_path=pid_path, log_path=log_path
    )
