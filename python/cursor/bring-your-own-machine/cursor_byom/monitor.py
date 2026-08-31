"""Delete a Daytona sandbox after its Cursor worker exits."""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from daytona import Daytona, DaytonaConfig

from .config import ConfigError, redact
from .sandbox_class import parse_sandbox_class
from .worker_windows import windows_inspection_command

_PROC_ROOT = "/proc"
_DEFAULT_POLL_SECONDS = 5.0
_MAX_INSPECTION_ERRORS = 3


@dataclass(frozen=True)
class MonitorConfig:
    """Validated host-only settings for one cleanup monitor."""

    daytona_api_key: str
    daytona_target: str | None
    sandbox_id: str
    worker_pid: str
    sandbox_class: str
    poll_seconds: float

    @classmethod
    def from_env(cls, environment: Mapping[str, str]) -> MonitorConfig:
        required = {
            name: _environment_value(environment, name)
            for name in (
                "DAYTONA_API_KEY",
                "SANDBOX_ID",
                "WORKER_PID",
                "SANDBOX_CLASS",
            )
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ConfigError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        worker_pid = required["WORKER_PID"]
        if worker_pid is None or not worker_pid.isdigit() or int(worker_pid) <= 0:
            raise ConfigError("WORKER_PID must be a positive numeric process ID")
        sandbox_class = parse_sandbox_class(required["SANDBOX_CLASS"]).value

        poll_seconds = _positive_float(
            environment,
            "MONITOR_POLL_SECONDS",
            _DEFAULT_POLL_SECONDS,
        )
        return cls(
            daytona_api_key=required["DAYTONA_API_KEY"] or "",
            daytona_target=_environment_value(environment, "DAYTONA_TARGET"),
            sandbox_id=required["SANDBOX_ID"] or "",
            worker_pid=worker_pid,
            sandbox_class=sandbox_class,
            poll_seconds=poll_seconds,
        )


def _environment_value(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    value = environment.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _positive_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    value = _environment_value(environment, name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as error:
        raise ConfigError(f"{name} must be a positive number; got {value!r}") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigError(f"{name} must be a positive number; got {value!r}")
    return parsed


def _is_not_found(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        return False
    try:
        return int(status_code) == 404
    except (TypeError, ValueError):
        return False


def _inspection_command(worker_pid: str, sandbox_class: str) -> str:
    if parse_sandbox_class(sandbox_class).value == "windows":
        return windows_inspection_command(worker_pid)

    stat_path = shlex.quote(f"{_PROC_ROOT}/{worker_pid}/stat")
    inner = " && ".join(
        (
            f"pid={shlex.quote(worker_pid)}",
            'test "$pid" -gt 0',
            'kill -0 "$pid" 2>/dev/null',
            f"stat=$(cat {stat_path} 2>/dev/null)",
            "fields=${stat##*) }",
            "state=${fields%% *}",
            'test "$state" != Z',
        )
    )
    return f"sh -c {shlex.quote(inner)}"


def monitor_worker(
    config: MonitorConfig,
    daytona: Any,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Wait for a live worker to exit, then delete its sandbox."""

    try:
        sandbox = daytona.get(config.sandbox_id)
    except Exception as error:
        return 0 if _is_not_found(error) else 1

    inspection_errors = 0
    command = _inspection_command(config.worker_pid, config.sandbox_class)
    while True:
        try:
            response = sandbox.process.exec(command, timeout=30)
        except Exception as error:
            if _is_not_found(error):
                return 0
            inspection_errors += 1
            if inspection_errors >= _MAX_INSPECTION_ERRORS:
                return 1
            sleep(config.poll_seconds)
            continue

        if getattr(response, "exit_code", 1) == 0:
            inspection_errors = 0
            sleep(config.poll_seconds)
            continue

        try:
            sandbox.delete()
        except Exception as error:
            return 0 if _is_not_found(error) else 1
        return 0


def main(argv: list[str] | None = None) -> int:
    """Run the non-interactive sandbox cleanup monitor."""
    parser = argparse.ArgumentParser(
        prog="monitor-cursor-byom-worker",
        description="Delete a Daytona sandbox after its Cursor worker exits.",
        epilog="Examples:\n  monitor-cursor-byom-worker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.parse_args(argv)

    config: MonitorConfig | None = None
    try:
        config = MonitorConfig.from_env(os.environ)
        daytona = Daytona(
            DaytonaConfig(
                api_key=config.daytona_api_key,
                target=config.daytona_target,
            )
        )
        status = monitor_worker(config, daytona)
    except Exception as error:
        secrets = (config.daytona_api_key,) if config is not None else ()
        print(
            "monitor-cursor-byom-worker: cleanup failed: "
            f"{redact(str(error), secrets)}",
            file=sys.stderr,
        )
        return 1

    if status != 0:
        print(
            "monitor-cursor-byom-worker: could not confirm worker exit or "
            f"delete sandbox {config.sandbox_id}",
            file=sys.stderr,
        )
        return status

    print(
        json.dumps(
            {"sandbox_id": config.sandbox_id, "status": "deleted"},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
