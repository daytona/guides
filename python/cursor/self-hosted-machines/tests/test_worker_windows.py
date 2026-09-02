from __future__ import annotations

import base64
import importlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FakeConfig:
    daytona_api_key: str = "host-daytona-key"
    cursor_api_key: str = "cursor-service-key"
    cursor_agent_worker_id: str = "worker-123"
    cursor_pool: str = "windows-pool"
    cursor_worker_name: str | None = "windows-worker"
    cursor_repo_urls: tuple[str, ...] = ("https://github.com/acme/repo.git",)
    idle_release_timeout_seconds: int = 900
    sandbox_launch_timeout_seconds: int = 60


class FakeFs:
    def __init__(self, pid_path: str) -> None:
        self.pid_path = pid_path.replace("\\", "/")
        self.uploads: list[tuple[bytes, str]] = []
        self.download_calls: list[str] = []

    def upload_file(self, source: bytes, destination: str) -> None:
        self.uploads.append((source, destination))

    def download_file(self, path: str) -> bytes:
        self.download_calls.append(path)
        if path == self.pid_path:
            return b"4242\r\n"
        raise FileNotFoundError(path)


class FakeProcess:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def exec(self, command: str, *, timeout: int) -> object:
        self.calls.append({"command": command, "timeout": timeout})
        return type("Response", (), {"exit_code": 0, "result": ""})()


class FakeSandbox:
    def __init__(self, pid_path: str) -> None:
        self.fs = FakeFs(pid_path)
        self.process = FakeProcess()


def decode_powershell(command: str) -> str:
    encoded = command.rsplit(" ", 1)[-1]
    return base64.b64decode(encoded).decode("utf-16le")


def test_windows_worker_launch_uses_baked_agent_and_secret_file_cleanup() -> None:
    module = importlib.import_module("cursor_self_hosted.worker_windows")
    sandbox = FakeSandbox(module.WINDOWS_WORKER_PID_PATH)
    sleeps: list[float] = []

    pid = module.start_windows_worker_process(
        sandbox,
        FakeConfig(),
        sleep=sleeps.append,
    )

    assert pid == "4242"
    assert sleeps == [module.WINDOWS_PID_POLL_SECONDS]
    assert len(sandbox.process.calls) == 2
    launch = sandbox.process.calls[0]
    assert launch["timeout"] == 60
    launch_script = decode_powershell(str(launch["command"]))
    assert module.WINDOWS_BOOTSTRAP_PATH in launch_script
    assert module.WINDOWS_WORKER_PID_PATH in launch_script
    inspection_script = decode_powershell(
        str(sandbox.process.calls[1]["command"])
    )
    assert "Get-Process -Id 4242" in inspection_script

    launch_upload = next(
        source
        for source, destination in sandbox.fs.uploads
        if destination == module.WINDOWS_LAUNCH_CONFIG_PATH
    )
    payload = json.loads(bytes(launch_upload).decode("utf-8"))
    assert payload["environment"] == {
        "CURSOR_AGENT_WORKER_ID": "worker-123",
        "CURSOR_API_KEY": "cursor-service-key",
        "CURSOR_WORKER_NAME": "windows-worker",
    }
    arguments = payload["arguments"]
    assert "index.js" in arguments
    assert "worker" in arguments
    assert "--pool windows-pool" in arguments
    assert "--worker-dir C:\\cursor\\workspace" in arguments
    assert "--on-session-start" in arguments
    assert "clone-cursor-self-hosted-repos.cmd" in arguments
    assert "host-daytona-key" not in json.dumps(payload)


def test_windows_inspection_checks_pid_and_expected_node_executable() -> None:
    module = importlib.import_module("cursor_self_hosted.worker_windows")

    script = decode_powershell(module.windows_inspection_command("4242"))

    assert "Get-Process -Id 4242" in script
    assert module.WINDOWS_AGENT_NODE_PATH in script
    assert "running" in script
    assert "exited" in script
    assert script.count("exit 1") == 2
