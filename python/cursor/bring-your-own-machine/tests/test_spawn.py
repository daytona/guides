from __future__ import annotations

import base64
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from cursor_byom import spawn as spawn_module
from cursor_byom.config import Config


@dataclass(frozen=True)
class FakeConfig:
    daytona_api_key: str = "test-daytona-key"
    snapshot_name: str = "cursor-worker-snapshot-test"
    cursor_api_key: str = "test-cursor-key"
    cursor_agent_worker_id: str = "worker-01"
    cursor_pool: str = "pool-test"
    cursor_request_id: str = "request-01"
    cursor_worker_name: str | None = "worker-test"
    cursor_api_url: str | None = "https://cursor.invalid"
    cursor_api_endpoint: str | None = "/agent"
    cursor_repo_url: str | None = "https://example.invalid/one.git"
    cursor_repo_urls: tuple[str, ...] = ("https://example.invalid/two.git",)
    idle_release_timeout_seconds: int = 600
    monitor_poll_seconds: float = 0.25
    sandbox_create_timeout_seconds: int = 120
    sandbox_launch_timeout_seconds: int = 30


class NotFoundError(Exception):
    status_code = 404


class FakeExecResponse:
    def __init__(self, exit_code: int = 0, result: str = "4242\n") -> None:
        self.exit_code = exit_code
        self.result = result


class FakeProcess:
    def __init__(
        self,
        outcome: FakeExecResponse
        | Exception
        | list[FakeExecResponse | Exception]
        | None = None,
    ) -> None:
        if isinstance(outcome, list):
            self.outcomes = list(outcome)
        else:
            self.outcomes = [outcome or FakeExecResponse()]
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
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeSandbox:
    def __init__(
        self,
        sandbox_id: str = "sandbox-123",
        name: str = "cursor-worker-01",
        process_outcome: FakeExecResponse
        | Exception
        | list[FakeExecResponse | Exception]
        | None = None,
        delete_error: Exception | None = None,
        lifecycle_events: list[str] | None = None,
    ) -> None:
        self.id = sandbox_id
        self.name = name
        self.process = FakeProcess(process_outcome)
        self.delete_error = delete_error
        self.lifecycle_events = lifecycle_events
        self.delete_calls = 0
        self.delete_timeouts: list[int | None] = []

    def delete(self, timeout: int | None = None) -> None:
        self.delete_calls += 1
        self.delete_timeouts.append(timeout)
        if self.lifecycle_events is not None:
            self.lifecycle_events.append(f"delete:{self.id}")
        if self.delete_error is not None:
            raise self.delete_error


class FakeSnapshotClient:
    def __init__(self, sandbox_class: str) -> None:
        self.sandbox_class = sandbox_class
        self.get_calls: list[str] = []

    def get(self, name: str) -> object:
        self.get_calls.append(name)
        return SimpleNamespace(
            name=name,
            sandbox_class=SimpleNamespace(value=self.sandbox_class),
        )


class FakeDaytona:
    def __init__(
        self,
        create_error: Exception | None = None,
        get_outcomes: list[FakeSandbox | Exception] | None = None,
        *,
        snapshot_class: str = "container",
    ) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.snapshot = FakeSnapshotClient(snapshot_class)
        self.create_error = create_error
        self.get_outcomes: list[FakeSandbox | Exception] | None = (
            list(get_outcomes) if get_outcomes is not None else None
        )
        self.get_calls: list[str] = []
        self.create_calls: list[tuple[Any, int | None]] = []
        self.created_sandboxes: list[FakeSandbox] = []
        self.lifecycle_events: list[str] = []

    def get(self, name: str) -> FakeSandbox:
        self.get_calls.append(name)
        if self.get_outcomes is not None:
            outcome = (
                self.get_outcomes.pop(0)
                if len(self.get_outcomes) > 1
                else self.get_outcomes[0]
            )
            if isinstance(outcome, Exception):
                status = getattr(outcome, "status_code", type(outcome).__name__)
                self.lifecycle_events.append(f"get-error:{status}")
                raise outcome
            self.lifecycle_events.append(f"get:{outcome.id}")
            return outcome

        try:
            sandbox = self.sandboxes[name]
        except KeyError:
            self.lifecycle_events.append("get-error:404")
            raise NotFoundError(name) from None
        self.lifecycle_events.append(f"get:{sandbox.id}")
        return sandbox

    def create(self, params: Any, timeout: int | None = None) -> FakeSandbox:
        self.create_calls.append((params, timeout))
        if self.create_error is not None:
            raise self.create_error
        name = parameter(params, "name")
        self.lifecycle_events.append(f"create:{name}")
        sandbox = FakeSandbox(name=name, lifecycle_events=self.lifecycle_events)
        self.sandboxes[name] = sandbox
        self.created_sandboxes.append(sandbox)
        return sandbox


def parameter(params: Any, name: str) -> Any:
    if isinstance(params, dict):
        return params[name]
    return getattr(params, name)


class ReleaseClaimTests(unittest.TestCase):
    def test_release_claim_posts_the_encoded_request_id_with_service_auth(self) -> None:
        release_claim = spawn_module.release_claim
        calls: list[tuple[Any, int]] = []

        class RecordingResponse:
            def __enter__(self) -> RecordingResponse:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

        def recording_urlopen(request: Any, *, timeout: int) -> RecordingResponse:
            calls.append((request, timeout))
            return RecordingResponse()

        service_key = "FAKE-CURSOR-SERVICE-KEY-DO-NOT-USE"
        config = cast(Any, FakeConfig(cursor_api_key=service_key))
        with patch.object(
            spawn_module.urllib.request,
            "urlopen",
            recording_urlopen,
        ):
            release_claim(config, "request/id ?#")

        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        self.assertEqual(
            request.full_url,
            "https://cursor.invalid/v0/private-workers/claims/"
            "request%2Fid%20%3F%23/release",
        )
        self.assertEqual(request.get_method(), "POST")
        authorization = request.get_header("Authorization")
        self.assertIsNotNone(authorization)
        scheme, encoded_credentials = authorization.split(" ", 1)
        self.assertEqual(scheme, "Basic")
        self.assertEqual(
            base64.b64decode(encoded_credentials).decode("utf-8"),
            f"{service_key}:",
        )
        self.assertEqual(request.data, b"")
        self.assertEqual(timeout, 30)


class MonitorLauncherTests(unittest.TestCase):
    def test_start_monitor_uses_current_python_and_host_cleanup_environment(self) -> None:
        start_monitor = spawn_module.start_monitor

        with patch.object(spawn_module.subprocess, "Popen") as popen:
            start_monitor(cast(Any, FakeConfig()), "sandbox-123", "4242")

        popen.assert_called_once_with(
            [sys.executable, "-m", "cursor_byom.monitor"],
            env={
                "DAYTONA_API_KEY": "test-daytona-key",
                "SANDBOX_ID": "sandbox-123",
                "WORKER_PID": "4242",
                "MONITOR_POLL_SECONDS": "0.25",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )


class SpawnWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config: Any = cast(Any, FakeConfig())
        self.released_claims: list[str] = []
        self.monitors: list[tuple[Any, ...]] = []

    def release_claim(self, request_id: str) -> None:
        self.released_claims.append(request_id)

    def start_monitor(
        self,
        config: FakeConfig,
        sandbox_id: str,
        worker_pid: str,
        *extra: str,
    ) -> None:
        self.monitors.append((config, sandbox_id, worker_pid, *extra))

    def spawn(self, daytona: FakeDaytona) -> Any:
        spawn_worker = spawn_module.spawn_worker
        return spawn_worker(
            self.config,
            daytona,
            release_claim=self.release_claim,
            start_monitor=cast(Any, self.start_monitor),
        )

    def test_existing_live_worker_sandbox_is_replaced_before_fresh_launch(
        self,
    ) -> None:
        daytona = FakeDaytona()
        old_sandbox = FakeSandbox(
            sandbox_id="sandbox-old",
            process_outcome=FakeExecResponse(result="5252\n"),
            lifecycle_events=daytona.lifecycle_events,
        )
        daytona.sandboxes["cursor-worker-01"] = old_sandbox
        daytona.get_outcomes = [old_sandbox, NotFoundError("cursor-worker-01")]

        result = self.spawn(daytona)

        self.assertEqual(
            daytona.get_calls,
            ["cursor-worker-01", "cursor-worker-01"],
        )
        self.assertEqual(old_sandbox.delete_calls, 1)
        self.assertEqual(old_sandbox.delete_timeouts, [120])
        self.assertEqual(old_sandbox.process.calls, [])
        self.assertEqual(
            daytona.lifecycle_events,
            [
                "get:sandbox-old",
                "delete:sandbox-old",
                "get-error:404",
                "create:cursor-worker-01",
            ],
        )
        self.assertEqual(len(daytona.create_calls), 1)
        self.assertEqual(len(daytona.created_sandboxes), 1)
        fresh_sandbox = daytona.created_sandboxes[0]
        self.assertIsNot(fresh_sandbox, old_sandbox)
        self.assertIs(daytona.sandboxes["cursor-worker-01"], fresh_sandbox)
        self.assertEqual(len(fresh_sandbox.process.calls), 1)
        self.assertIn("nohup", fresh_sandbox.process.calls[0]["command"])
        self.assertEqual(result.sandbox_id, "sandbox-123")
        self.assertEqual(result.sandbox_name, "cursor-worker-01")
        self.assertEqual(result.worker_id, "worker-01")
        self.assertEqual(result.request_id, "request-01")
        self.assertEqual(self.monitors, [(self.config, "sandbox-123", "4242")])

    def test_create_waits_until_replacement_get_returns_not_found(self) -> None:
        daytona = FakeDaytona()
        old_sandbox = FakeSandbox(
            sandbox_id="sandbox-old",
            lifecycle_events=daytona.lifecycle_events,
        )
        daytona.sandboxes["cursor-worker-01"] = old_sandbox
        daytona.get_outcomes = [
            old_sandbox,
            old_sandbox,
            NotFoundError("cursor-worker-01"),
        ]

        self.spawn(daytona)

        self.assertEqual(
            daytona.lifecycle_events,
            [
                "get:sandbox-old",
                "delete:sandbox-old",
                "get:sandbox-old",
                "get-error:404",
                "create:cursor-worker-01",
            ],
        )
        self.assertEqual(
            daytona.get_calls,
            ["cursor-worker-01", "cursor-worker-01", "cursor-worker-01"],
        )
        self.assertEqual(len(daytona.create_calls), 1)

    def test_replacement_timeout_releases_claim_without_creating_sandbox(
        self,
    ) -> None:
        self.config = FakeConfig(sandbox_create_timeout_seconds=0)
        daytona = FakeDaytona()
        old_sandbox = FakeSandbox(
            sandbox_id="sandbox-old",
            lifecycle_events=daytona.lifecycle_events,
        )
        daytona.sandboxes["cursor-worker-01"] = old_sandbox
        daytona.get_outcomes = [old_sandbox]

        with self.assertRaises(TimeoutError) as raised:
            self.spawn(daytona)

        message = str(raised.exception).lower()
        self.assertIn("timed out", message)
        self.assertIn("cursor-worker-01", message)
        self.assertEqual(old_sandbox.delete_calls, 1)
        self.assertEqual(daytona.create_calls, [])
        self.assertEqual(daytona.created_sandboxes, [])
        self.assertEqual(self.released_claims, ["request-01"])
        self.assertEqual(self.monitors, [])

    def test_create_uses_snapshot_labels_auto_stop_fallback_and_delete_on_stop(self) -> None:
        daytona = FakeDaytona()

        self.spawn(daytona)

        self.assertEqual(len(daytona.create_calls), 1)
        params, timeout = daytona.create_calls[0]
        self.assertEqual(parameter(params, "name"), "cursor-worker-01")
        self.assertEqual(parameter(params, "snapshot"), "cursor-worker-snapshot-test")
        self.assertEqual(
            parameter(params, "labels"),
            {
                "cursor.worker_id": "worker-01",
                "cursor.request_id": "request-01",
                "cursor.pool": "pool-test",
            },
        )
        self.assertGreater(parameter(params, "auto_stop_interval"), 0)
        self.assertGreaterEqual(
            parameter(params, "auto_stop_interval") * 60,
            self.config.idle_release_timeout_seconds,
        )
        self.assertEqual(parameter(params, "auto_delete_interval"), 0)
        self.assertEqual(timeout, 120)

    def test_snapshot_class_drives_labels_result_and_monitor(self) -> None:
        daytona = FakeDaytona(snapshot_class="linux-vm")

        result = self.spawn(daytona)

        params, _ = daytona.create_calls[0]
        self.assertEqual(
            parameter(params, "labels")["cursor.sandbox_class"],
            "linux-vm",
        )
        self.assertEqual(result.sandbox_class, "linux-vm")
        self.assertEqual(
            self.monitors,
            [(self.config, "sandbox-123", "4242", "linux-vm")],
        )

    def test_worker_shell_commands_use_non_login_sh(self) -> None:
        launch_command = spawn_module._worker_launch_command

        command = launch_command(self.config)

        self.assertTrue(command.startswith("sh -c "))
        self.assertNotIn("sh -lc", command)

    def test_detached_launch_passes_only_cursor_environment_into_the_sandbox(self) -> None:
        daytona = FakeDaytona()

        self.spawn(daytona)

        sandbox = daytona.sandboxes["cursor-worker-01"]
        self.assertEqual(len(sandbox.process.calls), 1)
        launch = sandbox.process.calls[0]
        self.assertEqual(launch["cwd"], "/home/daytona/workspace")
        self.assertEqual(launch["timeout"], 30)
        self.assertIn("nohup", launch["command"])
        self.assertIn("&", launch["command"])
        self.assertEqual(
            launch["env"],
            {
                "CURSOR_API_KEY": "test-cursor-key",
                "CURSOR_AGENT_WORKER_ID": "worker-01",
                "CURSOR_WORKER_NAME": "worker-test",
            },
        )
        self.assertNotIn("DAYTONA_API_KEY", launch["env"])
        self.assertNotIn("SNAPSHOT_NAME", launch["env"])
        self.assertNotIn("CURSOR_API_URL", launch["env"])
        self.assertNotIn("CURSOR_API_ENDPOINT", launch["env"])
        self.assertNotIn("CURSOR_REQUEST_ID", launch["env"])
        self.assertNotIn("CURSOR_POOL", launch["env"])
        self.assertNotIn("CURSOR_REPO_URL", launch["env"])
        self.assertNotIn("CURSOR_REPO_URLS", launch["env"])

    def test_real_config_passes_integer_launch_timeout_to_process_exec(
        self,
    ) -> None:
        config = Config.from_env(
            {
                "DAYTONA_API_KEY": "test-daytona-key",
                "SNAPSHOT_NAME": "cursor-worker-snapshot-test",
                "CURSOR_API_KEY": "test-cursor-key",
                "CURSOR_AGENT_WORKER_ID": "worker-01",
                "CURSOR_POOL": "pool-test",
                "CURSOR_REQUEST_ID": "request-01",
                "SANDBOX_LAUNCH_TIMEOUT_SECONDS": "30",
            }
        )
        daytona = FakeDaytona()
        spawn_worker = spawn_module.spawn_worker

        spawn_worker(
            config,
            daytona,
            release_claim=self.release_claim,
            start_monitor=cast(Any, self.start_monitor),
        )

        launch_timeout = daytona.sandboxes["cursor-worker-01"].process.calls[0][
            "timeout"
        ]
        self.assertEqual(launch_timeout, 30)
        self.assertIs(type(launch_timeout), int)

    def test_success_starts_host_monitor_and_returns_all_identifiers(self) -> None:
        daytona = FakeDaytona()

        result = self.spawn(daytona)

        self.assertEqual(result.sandbox_id, "sandbox-123")
        self.assertEqual(result.sandbox_name, "cursor-worker-01")
        self.assertEqual(result.worker_id, "worker-01")
        self.assertEqual(result.request_id, "request-01")
        self.assertEqual(self.monitors, [(self.config, "sandbox-123", "4242")])

    def test_detached_launch_rejects_zombie_worker_during_startup_check(
        self,
    ) -> None:
        launch_command = spawn_module._worker_launch_command

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            pid_path = temp_path / "worker.pid"
            log_path = temp_path / "worker.log"
            proc_root = temp_path / "proc"
            worker_script = (
                "import os\n"
                "from pathlib import Path\n"
                f"proc_root = Path({str(proc_root)!r})\n"
                "pid = os.getpid()\n"
                "stat_path = proc_root / str(pid) / 'stat'\n"
                "stat_path.parent.mkdir(parents=True)\n"
                "stat_path.write_text(f'{pid} (sleep) Z 1 2 3\\n', encoding='utf-8')\n"
                "os.execlp('sleep', 'sleep', '60')\n"
            )
            worker_pid: int | None = None
            try:
                with (
                    patch.object(spawn_module, "_WORKER_PID_PATH", str(pid_path)),
                    patch.object(spawn_module, "_WORKER_LOG_PATH", str(log_path)),
                    patch.object(spawn_module, "_PROC_ROOT", str(proc_root)),
                    patch.object(spawn_module, "_WORKER_STARTUP_DELAY_SECONDS", 1),
                    patch.object(
                        spawn_module,
                        "worker_command",
                        return_value=[sys.executable, "-c", worker_script],
                    ),
                ):
                    completed = subprocess.run(
                        launch_command(self.config),
                        shell=True,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                worker_pid = int(pid_path.read_text(encoding="utf-8").strip())
                stat_path = proc_root / str(worker_pid) / "stat"
                self.assertTrue(stat_path.is_file())
                os.kill(worker_pid, 0)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
            finally:
                if worker_pid is None and pid_path.is_file():
                    worker_pid = int(pid_path.read_text(encoding="utf-8").strip())
                if worker_pid is not None:
                    try:
                        os.kill(worker_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    def test_create_failure_releases_the_claim_for_the_current_request(self) -> None:
        daytona = FakeDaytona(create_error=RuntimeError("create failed"))

        with self.assertRaisesRegex(RuntimeError, "create failed"):
            self.spawn(daytona)

        self.assertEqual(self.released_claims, ["request-01"])
        self.assertEqual(self.monitors, [])

    def test_launch_failure_releases_claim_and_deletes_created_sandbox(self) -> None:
        daytona = FakeDaytona()
        failed = FakeSandbox(
            name="cursor-worker-01",
            process_outcome=FakeExecResponse(exit_code=7, result="launch failed"),
        )
        original_create = daytona.create

        def create_failed_sandbox(params: Any, timeout: int | None = None) -> FakeSandbox:
            original_create(params, timeout)
            daytona.sandboxes["cursor-worker-01"] = failed
            return failed

        daytona.create = create_failed_sandbox  # type: ignore[method-assign]

        with self.assertRaises(Exception):
            self.spawn(daytona)

        self.assertEqual(self.released_claims, ["request-01"])
        self.assertEqual(failed.delete_calls, 1)
        self.assertEqual(self.monitors, [])

    def test_rollback_warns_with_redaction_and_preserves_primary_exec_error(
        self,
    ) -> None:
        daytona_key = "FAKE-DAYTONA-ROLLBACK-KEY-DO-NOT-USE"
        cursor_key = "FAKE-CURSOR-ROLLBACK-KEY-DO-NOT-USE"
        config = cast(
            Any,
            FakeConfig(
                daytona_api_key=daytona_key,
                cursor_api_key=cursor_key,
            ),
        )
        daytona = FakeDaytona()
        exec_failure = RuntimeError("exec failed")
        release_failure = ValueError(f"release failed: {cursor_key}")
        delete_failure = RuntimeError(f"delete failed: {daytona_key}")
        failed = FakeSandbox(
            name="cursor-worker-01",
            process_outcome=exec_failure,
            delete_error=delete_failure,
        )
        original_create = daytona.create
        release_attempts: list[str] = []

        def create_failed_sandbox(
            params: Any, timeout: int | None = None
        ) -> FakeSandbox:
            original_create(params, timeout)
            daytona.sandboxes["cursor-worker-01"] = failed
            return failed

        def fail_release(request_id: str) -> None:
            release_attempts.append(request_id)
            raise release_failure

        daytona.create = create_failed_sandbox  # type: ignore[method-assign]
        spawn_worker = spawn_module.spawn_worker
        stderr = io.StringIO()

        with (
            patch("sys.stderr", stderr),
            self.assertRaises(RuntimeError) as raised,
        ):
            spawn_worker(
                config,
                daytona,
                release_claim=fail_release,
                start_monitor=cast(Any, self.start_monitor),
            )

        self.assertIs(raised.exception, exec_failure)
        self.assertEqual(release_attempts, ["request-01"])
        self.assertEqual(failed.delete_calls, 1)
        self.assertEqual(self.monitors, [])

        warnings = stderr.getvalue().splitlines()
        self.assertEqual(len(warnings), 2)
        self.assertTrue(
            all("warning" in warning.lower() for warning in warnings)
        )
        self.assertTrue(
            all("<redacted>" in warning for warning in warnings)
        )
        self.assertTrue(any("release" in warning.lower() for warning in warnings))
        self.assertTrue(any("delete" in warning.lower() for warning in warnings))
        self.assertNotIn(cursor_key, stderr.getvalue())
        self.assertNotIn(daytona_key, stderr.getvalue())

    def test_success_never_releases_the_claim(self) -> None:
        self.spawn(FakeDaytona())

        self.assertEqual(self.released_claims, [])


class SpawnCommandTests(unittest.TestCase):
    def test_main_prints_exactly_one_json_result_record(self) -> None:
        main = spawn_module.main
        result = SimpleNamespace(
            sandbox_id="sandbox-123",
            sandbox_name="cursor-worker-01",
            worker_id="worker-01",
            request_id="request-01",
        )
        output = io.StringIO()

        class ConfigFactory:
            @staticmethod
            def from_env(mapping: Any = None) -> FakeConfig:
                return FakeConfig()

        with (
            patch.object(spawn_module, "Config", ConfigFactory, create=True),
            patch.object(spawn_module, "Daytona", lambda *args, **kwargs: FakeDaytona(), create=True),
            patch.object(spawn_module, "release_claim", lambda *args: None, create=True),
            patch.object(spawn_module, "start_monitor", lambda *args: None, create=True),
            patch.object(spawn_module, "spawn_worker", return_value=result, create=True),
            patch("sys.stdout", output),
        ):
            status = main([])

        records = [line for line in output.getvalue().splitlines() if line]
        self.assertEqual(status, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            json.loads(records[0]),
            {
                "sandbox_id": "sandbox-123",
                "sandbox_name": "cursor-worker-01",
                "worker_id": "worker-01",
                "request_id": "request-01",
            },
        )

    def test_main_redacts_both_api_keys_from_spawn_failures(self) -> None:
        main = spawn_module.main
        daytona_key = "FAKE-DAYTONA-API-KEY-DO-NOT-USE"
        cursor_key = "FAKE-CURSOR-API-KEY-DO-NOT-USE"
        config = FakeConfig(
            daytona_api_key=daytona_key,
            cursor_api_key=cursor_key,
        )
        error_output = io.StringIO()

        class ConfigFactory:
            @staticmethod
            def from_env(mapping: Any = None) -> FakeConfig:
                return config

        failure = RuntimeError(
            f"failed with Daytona key {daytona_key} "
            f"and Cursor key {cursor_key}"
        )
        with (
            patch.object(spawn_module, "Config", ConfigFactory, create=True),
            patch.object(
                spawn_module,
                "Daytona",
                lambda *args, **kwargs: FakeDaytona(),
                create=True,
            ),
            patch.object(
                spawn_module,
                "spawn_worker",
                side_effect=failure,
                create=True,
            ),
            patch("sys.stderr", error_output),
        ):
            status = main([])

        stderr = error_output.getvalue()
        self.assertEqual(status, 1)
        self.assertEqual(stderr.count("<redacted>"), 2)
        self.assertNotIn(daytona_key, stderr)
        self.assertNotIn(cursor_key, stderr)


if __name__ == "__main__":
    unittest.main()
