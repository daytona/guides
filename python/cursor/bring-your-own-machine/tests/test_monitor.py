from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from cursor_byom import monitor as monitor_module


@dataclass(frozen=True)
class FakeMonitorConfig:
    sandbox_id: str = "sandbox-123"
    worker_pid: str = "4242"
    poll_seconds: float = 0.25



def test_monitor_config_keeps_snapshot_sandbox_class() -> None:
    config = monitor_module.MonitorConfig.from_env(
        {
            "DAYTONA_API_KEY": "daytona-key-test",
            "SANDBOX_ID": "sandbox-123",
            "WORKER_PID": "4242",
            "SANDBOX_CLASS": "windows",
        }
    )

    assert config.sandbox_class == "windows"

class NotFoundError(Exception):
    status_code = 404


class TransientInspectionError(Exception):
    status_code = 503


class FakeExecResponse:
    def __init__(self, exit_code: int, result: str = "") -> None:
        self.exit_code = exit_code
        self.result = result


class FakeProcess:
    def __init__(self, outcomes: list[FakeExecResponse | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeExecResponse:
        self.calls.append(
            {"command": command, "cwd": cwd, "env": env, "timeout": timeout}
        )
        if not self.outcomes:
            raise AssertionError("monitor inspected the worker more times than expected")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeSandbox:
    def __init__(
        self,
        outcomes: list[FakeExecResponse | Exception],
        delete_error: Exception | None = None,
    ) -> None:
        self.process = FakeProcess(outcomes)
        self.delete_error = delete_error
        self.delete_calls = 0

    def delete(self, timeout: int | None = None) -> None:
        self.delete_calls += 1
        if self.delete_error is not None:
            raise self.delete_error


class FakeDaytona:
    def __init__(
        self,
        sandbox: FakeSandbox | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.get_error = get_error
        self.get_calls: list[str] = []

    def get(self, sandbox_id: str) -> FakeSandbox:
        self.get_calls.append(sandbox_id)
        if self.get_error is not None:
            raise self.get_error
        if self.sandbox is None:
            raise AssertionError("test did not provide a sandbox")
        return self.sandbox


class MonitorWorkerTests(unittest.TestCase):
    def monitor(
        self,
        daytona: FakeDaytona,
        sleeps: list[float],
        config: FakeMonitorConfig | None = None,
    ) -> int:
        monitor_worker = monitor_module.monitor_worker
        return monitor_worker(
            cast(Any, config or FakeMonitorConfig()),
            daytona,
            sleep=cast(Any, sleeps.append),
        )

    def start_sleep(self) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            ["sleep", "60"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def terminate() -> None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        self.addCleanup(terminate)
        return process

    def test_inspection_command_uses_non_login_shell(self) -> None:
        inspection_command = monitor_module._inspection_command

        command = inspection_command("4242")

        self.assertTrue(command.startswith("sh -c "))
        self.assertNotIn("sh -lc", command)

    def test_windows_inspection_uses_windows_process_check(self) -> None:
        with patch.object(
            monitor_module,
            "windows_inspection_command",
            return_value="windows-check",
            create=True,
        ) as windows_check:
            command = monitor_module._inspection_command("4242", "windows")

        self.assertEqual(command, "windows-check")
        windows_check.assert_called_once_with("4242")


    def test_inspection_fails_closed_when_live_process_stat_is_missing(self) -> None:
        inspection_command = monitor_module._inspection_command
        process = self.start_sleep()

        with (
            tempfile.TemporaryDirectory() as proc_root,
            patch.object(monitor_module, "_PROC_ROOT", proc_root),
        ):
            completed = subprocess.run(
                inspection_command(str(process.pid)),
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertIsNone(process.poll())
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")

    def test_inspection_rejects_zombie_stat_for_live_process(self) -> None:
        inspection_command = monitor_module._inspection_command
        process = self.start_sleep()

        with tempfile.TemporaryDirectory() as proc_root:
            stat_path = Path(proc_root, str(process.pid), "stat")
            stat_path.parent.mkdir()
            stat_path.write_text(
                f"{process.pid} (sleep) Z 1 2 3\n",
                encoding="utf-8",
            )
            with patch.object(monitor_module, "_PROC_ROOT", proc_root):
                completed = subprocess.run(
                    inspection_command(str(process.pid)),
                    shell=True,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

        self.assertIsNone(process.poll())
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")

    def test_worker_exit_deletes_the_sandbox(self) -> None:
        sandbox = FakeSandbox(
            [
                FakeExecResponse(exit_code=0, result="running"),
                FakeExecResponse(exit_code=1, result="exited"),
            ]
        )
        daytona = FakeDaytona(sandbox)
        sleeps: list[float] = []

        status = self.monitor(daytona, sleeps)

        self.assertEqual(status, 0)
        self.assertEqual(daytona.get_calls, ["sandbox-123"])
        self.assertEqual(len(sandbox.process.calls), 2)
        for inspection in sandbox.process.calls:
            self.assertIn("4242", inspection["command"])
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(sandbox.delete_calls, 1)

    def test_missing_sandbox_is_already_successfully_cleaned_up(self) -> None:
        daytona = FakeDaytona(get_error=NotFoundError("sandbox absent"))
        sleeps: list[float] = []

        status = self.monitor(daytona, sleeps)

        self.assertEqual(status, 0)
        self.assertEqual(daytona.get_calls, ["sandbox-123"])
        self.assertEqual(sleeps, [])

    def test_successful_inspections_reset_the_transient_error_budget(self) -> None:
        sandbox = FakeSandbox(
            [
                TransientInspectionError("first temporary service failure"),
                FakeExecResponse(exit_code=0, result="running"),
                TransientInspectionError("second temporary service failure"),
                FakeExecResponse(exit_code=0, result="running"),
                TransientInspectionError("third temporary service failure"),
                FakeExecResponse(exit_code=0, result="running"),
                FakeExecResponse(exit_code=1, result="exited"),
            ]
        )
        sleeps: list[float] = []

        status = self.monitor(FakeDaytona(sandbox), sleeps)

        self.assertEqual(status, 0)
        self.assertEqual(len(sandbox.process.calls), 7)
        self.assertEqual(sleeps, [0.25] * 6)
        self.assertEqual(sandbox.delete_calls, 1)

    def test_not_found_during_delete_is_idempotent_success(self) -> None:
        sandbox = FakeSandbox(
            [FakeExecResponse(exit_code=1, result="exited")],
            delete_error=NotFoundError("deleted concurrently"),
        )

        status = self.monitor(FakeDaytona(sandbox), [])

        self.assertEqual(status, 0)
        self.assertEqual(sandbox.delete_calls, 1)


if __name__ == "__main__":
    unittest.main()
