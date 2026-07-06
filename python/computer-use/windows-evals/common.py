"""Shared Daytona helpers for the Windows computer-use eval guide."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaConfig, Sandbox


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load KEY=VALUE lines from .env without overriding exported variables."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('\"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(Path(__file__).with_name(".env"))
load_dotenv()


def get_client() -> Daytona:
    """Create a Daytona client from DAYTONA_API_KEY and optional DAYTONA_API_URL."""
    api_url = os.environ.get("DAYTONA_API_URL")
    if api_url:
        return Daytona(
            DaytonaConfig(
                api_key=os.environ.get("DAYTONA_API_KEY"),
                api_url=api_url,
            )
        )
    return Daytona()


def create_sandbox(
    client,
    snapshot: str,
    name: str | None = None,
    labels: dict[str, str] | None = None,
) -> Sandbox:
    """Create a sandbox from a VM snapshot."""
    return client.create(
        CreateSandboxFromSnapshotParams(
            snapshot=snapshot,
            name=name,
            labels=labels,
        )
    )



def ps_exec(sandbox, script: str, timeout: int = 120):
    """Run PowerShell safely via -EncodedCommand."""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"
    return sandbox.process.exec(command, timeout=timeout)


def ps_ok(sandbox, script: str, timeout: int = 120) -> tuple[bool, str]:
    """Run PowerShell and return (success, cleaned stdout text)."""
    response = ps_exec(sandbox, script, timeout=timeout)
    result = getattr(response, "result", "") or ""
    return getattr(response, "exit_code", None) == 0, strip_clixml_noise(str(result))


def start_computer_use(sandbox, timeout: int = 60) -> None:
    """Start computer-use services and wait until their status is active."""
    sandbox.computer_use.start()
    deadline = time.monotonic() + timeout
    last_status: Any = None
    last_error: Exception | None = None

    while True:
        try:
            response = sandbox.computer_use.get_status()
            last_error = None
            last_status = _field(response, "status")
            if str(last_status).lower() == "active":
                return
        except Exception as exc:  # noqa: BLE001 - surface the last SDK error on timeout.
            last_error = exc

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(2.0, remaining))

    if last_error is not None:
        raise TimeoutError(f"computer-use did not become active within {timeout}s: {last_error}")
    raise TimeoutError(f"computer-use did not become active within {timeout}s; last status={last_status!r}")


def screenshot_png(sandbox) -> bytes:
    """Take a full-screen screenshot and return decoded PNG bytes."""
    response = sandbox.computer_use.screenshot.take_full_screen()
    screenshot = _field(response, "screenshot")
    if not isinstance(screenshot, str):
        raise TypeError("expected screenshot response field to be a base64 string")
    return base64.b64decode(screenshot)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


def strip_clixml_noise(text: str) -> str:
    """Remove PowerShell progress CLIXML while keeping stdout that precedes it."""
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "#< CLIXML":
            continue
        if stripped.startswith("<Objs ") and "http://schemas.microsoft.com/powershell/" in stripped:
            break
        cleaned.append(line)
    return "\n".join(cleaned).rstrip()
