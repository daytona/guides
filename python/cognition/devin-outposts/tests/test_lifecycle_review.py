from __future__ import annotations

import base64
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from devin_outposts.config import Config, RepoSpec
from devin_outposts.orchestrator import Orchestrator
from devin_outposts.queue import QueueEntry
from devin_outposts.sandbox import is_not_found, sandbox_name_for
from devin_outposts.worker import (
    WorkerHandle,
    attach_worker_process,
    poll_worker_process,
)

SESSION_ID = "session-c0ffee"
REMOTE_SHA = "c0ffee1234"


class ExecResponse:
    def __init__(self, exit_code: int = 0, result: str = "") -> None:
        self.exit_code = exit_code
        self.result = result


def make_config(state_dir: Path, **changes: Any) -> Config:
    config = Config(
        devin_outposts_token="outposts-secret",
        devin_api_url="https://example.test/api",
        outpost_id="outpost-1",
        snapshot_name="snapshot-1",
        max_concurrent_sessions=2,
        state_dir=state_dir,
        acceptor_id="acceptor-1",
        workdir="/workspace",
        devin_chrome_path="/usr/bin/chromium",
        repos=(),
        git_username=None,
        git_token=None,
        worker_poll_seconds=0.01,
    )
    return replace(config, **changes)


class NullQueue:
    pass


class ImmediateEvent(threading.Event):
    def wait(self, timeout: float | None = None) -> bool:
        return False


class SandboxNamingTests(unittest.TestCase):
    def test_names_remain_readable_deterministic_bounded_and_collision_resistant(
        self,
    ) -> None:
        slash_name = sandbox_name_for("a/b")
        hyphen_name = sandbox_name_for("a-b")

        self.assertTrue(slash_name.startswith("devin-a-b-"))
        self.assertTrue(hyphen_name.startswith("devin-a-b-"))
        self.assertNotEqual(slash_name, hyphen_name)
        self.assertEqual(slash_name, sandbox_name_for("a/b"))
        self.assertLessEqual(len(sandbox_name_for("x" * 500)), 63)

    def test_not_found_detection_ignores_message_text_and_broad_class_names(
        self,
    ) -> None:
        class ServiceFailure(Exception):
            pass

        class CacheNotFoundError(Exception):
            pass

        class StatusError(Exception):
            status_code = 404

        self.assertFalse(
            is_not_found(ServiceFailure("upstream said Not Found while parsing"))
        )
        self.assertFalse(is_not_found(CacheNotFoundError("Not Found")))
        self.assertTrue(is_not_found(StatusError("missing")))


class LabelledSandbox:
    def __init__(self, labels: dict[str, str], state: str = "stopped") -> None:
        self.labels = labels.copy()
        self.state = state
        self.started = False
        self.set_labels_calls: list[dict[str, str]] = []

    def set_labels(self, labels: dict[str, str]) -> None:
        self.set_labels_calls.append(labels)
        self.labels = labels.copy()

    def start(self, timeout: int | None = None) -> None:
        self.started = True
        self.state = "started"


class LookupDaytona:
    def __init__(self, sandbox: LabelledSandbox) -> None:
        self.sandbox = sandbox

    def get(self, name: str) -> LabelledSandbox:
        return self.sandbox


class SandboxAdoptionTests(unittest.TestCase):
    def test_same_name_resource_with_foreign_labels_is_never_mutated_or_started(
        self,
    ) -> None:
        for foreign_labels in (
            {"devin.session_id": "another-session", "devin.outpost_id": "outpost-1"},
            {"devin.session_id": SESSION_ID, "devin.outpost_id": "another-outpost"},
            {},
        ):
            with self.subTest(labels=foreign_labels):
                sandbox = LabelledSandbox(foreign_labels)
                with tempfile.TemporaryDirectory() as state_dir:
                    orchestrator = Orchestrator(
                        make_config(Path(state_dir)),
                        NullQueue(),
                        LookupDaytona(sandbox),
                    )
                    self.addCleanup(orchestrator._serve_executor.shutdown, wait=True)
                    with self.assertRaisesRegex(RuntimeError, "labels do not match"):
                        orchestrator.ensure_sandbox(SESSION_ID, create_if_missing=False)

                self.assertFalse(sandbox.started)
                self.assertEqual(sandbox.set_labels_calls, [])
                self.assertEqual(sandbox.labels, foreign_labels)


class RecordingProcess:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def exec(self, command: str, timeout: int | None = None) -> ExecResponse:
        self.commands.append(command)
        if command.startswith("test -e "):
            return ExecResponse(1)
        return ExecResponse(0)


class RecordingGit:
    def __init__(self) -> None:
        self.clones: list[dict[str, Any]] = []

    def clone(self, **kwargs: Any) -> None:
        self.clones.append(kwargs)


class RepoSandbox:
    def __init__(self) -> None:
        self.process = RecordingProcess()
        self.git = RecordingGit()


class RepositoryPlacementTests(unittest.TestCase):
    def test_linux_repositories_clone_directly_below_workdir(self) -> None:
        sandbox = RepoSandbox()
        with tempfile.TemporaryDirectory() as state_dir:
            config = make_config(
                Path(state_dir),
                workdir="/workspace",
                repos=(RepoSpec("https://example.test/team/project.git", "project"),),
            )
            orchestrator = Orchestrator(config, NullQueue(), object())
            self.addCleanup(orchestrator._serve_executor.shutdown, wait=True)
            orchestrator.clone_configured_repos(sandbox, "linux")

        self.assertEqual(sandbox.git.clones[0]["path"], "/workspace/project")
        self.assertIn("mkdir -p /workspace", sandbox.process.commands)


class LifecycleSandbox:
    def __init__(self, session_id: str) -> None:
        self.labels = {"devin.session_id": session_id, "devin.outpost_id": "outpost-1"}
        self.state = "started"
        self.stopped = False
        self.deleted = False

    def stop(self, timeout: int | None = None) -> None:
        self.stopped = True
        self.state = "stopped"

    def delete(self, timeout: int | None = None) -> None:
        self.deleted = True
        self.state = "deleted"


class JanitorDaytona:
    def __init__(self, sandbox: LifecycleSandbox) -> None:
        self.sandbox = sandbox

    def list(self, query: Any) -> list[LifecycleSandbox]:
        return [self.sandbox]


class Queue404(Exception):
    status_code = 404


class JanitorQueue:
    def __init__(self, entry: QueueEntry | None) -> None:
        self.entry = entry

    def get(self, session_id: str) -> QueueEntry:
        if self.entry is None:
            raise Queue404(session_id)
        return self.entry


class JanitorTests(unittest.TestCase):
    def test_absent_entry_is_stopped_while_observed_termination_is_deleted(
        self,
    ) -> None:
        cases = (
            (None, True, False),
            (
                QueueEntry(session_id=SESSION_ID, session_status="terminated"),
                False,
                True,
            ),
        )
        for entry, expect_stopped, expect_deleted in cases:
            with self.subTest(entry=entry):
                sandbox = LifecycleSandbox(SESSION_ID)
                with tempfile.TemporaryDirectory() as state_dir:
                    orchestrator = Orchestrator(
                        make_config(Path(state_dir)),
                        JanitorQueue(entry),
                        JanitorDaytona(sandbox),
                    )
                    self.addCleanup(orchestrator._serve_executor.shutdown, wait=True)
                    with patch(
                        "devin_outposts.orchestrator.ListSandboxesQuery",
                        side_effect=lambda **kwargs: kwargs,
                    ):
                        orchestrator.run_janitor_once()

                self.assertEqual(sandbox.stopped, expect_stopped)
                self.assertEqual(sandbox.deleted, expect_deleted)


class BoundedServeTests(unittest.TestCase):
    def test_executor_bounds_threads_and_eventually_serves_every_pending_entry(
        self,
    ) -> None:
        gate = threading.Event()
        first_wave_started = threading.Event()
        all_completed = threading.Event()
        lock = threading.Lock()
        started: list[str] = []
        completed: list[str] = []
        entries = [QueueEntry(session_id=f"session-{index}") for index in range(8)]
        baseline_workers = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name.startswith("devin-outposts-worker")
        }

        with tempfile.TemporaryDirectory() as state_dir:
            orchestrator = Orchestrator(
                make_config(Path(state_dir), max_concurrent_sessions=2),
                NullQueue(),
                object(),
            )
            self.addCleanup(orchestrator._serve_executor.shutdown, wait=True)
            self.addCleanup(gate.set)

            def blocked_serve(
                entry: QueueEntry, *, already_claimed: bool = False
            ) -> None:
                del already_claimed
                with lock:
                    started.append(entry.session_id or "")
                    if len(started) == 2:
                        first_wave_started.set()
                gate.wait()
                with lock:
                    completed.append(entry.session_id or "")
                    if len(completed) == len(entries):
                        all_completed.set()

            orchestrator.serve = blocked_serve  # type: ignore[method-assign]
            for entry in entries:
                orchestrator._spawn_serve(entry, already_claimed=False)

            self.assertTrue(
                first_wave_started.wait(5), "executor workers did not start"
            )
            new_workers = [
                thread
                for thread in threading.enumerate()
                if thread.name.startswith("devin-outposts-worker")
                and thread.ident not in baseline_workers
            ]
            self.assertEqual(len(new_workers), 2)

            gate.set()
            self.assertTrue(
                all_completed.wait(5), "pending sessions were not all served"
            )
            self.assertCountEqual(completed, [entry.session_id for entry in entries])


class PollingProcess:
    def __init__(
        self,
        response: ExecResponse | None = None,
        error: Exception | None = None,
        actual_executable: str | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.actual_executable = actual_executable
        self.commands: list[str] = []

    def exec(self, command: str, timeout: int | None = None) -> ExecResponse:
        decoded = command
        if "-EncodedCommand" in command:
            decoded = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16le")
        self.commands.append(decoded)
        if self.error is not None:
            raise self.error
        if self.actual_executable is not None:
            result = "running" if self.actual_executable in decoded else "exited"
            return ExecResponse(0, result)
        return self.response or ExecResponse(0, "unknown")


class ProcessSandbox:
    def __init__(self, process: PollingProcess) -> None:
        self.process = process


class WorkerPollingTests(unittest.TestCase):
    def config(self) -> Config:
        state_dir = self.enterContext(tempfile.TemporaryDirectory())
        return make_config(Path(state_dir))

    def worker(self, platform: str = "linux") -> WorkerHandle:
        pid_path = (
            r"C:\ProgramData\devin-outposts\sessions\session-c0ffee\worker.pid"
            if platform == "windows"
            else "/tmp/devin-outposts/session-c0ffee.pid"
        )
        return WorkerHandle(
            sandbox_name=sandbox_name_for(SESSION_ID),
            pid="4242",
            pid_path=pid_path,
            log_path="worker.log",
            platform=platform,
            remote_sha=REMOTE_SHA,
        )

    def test_poll_errors_and_unrecognized_results_are_unknown_not_exited(self) -> None:
        cases = (
            PollingProcess(error=RuntimeError("transient exec failure")),
            PollingProcess(response=ExecResponse(1, "exited")),
            PollingProcess(response=ExecResponse(0, "temporary-unavailable")),
        )
        for process in cases:
            with self.subTest(process=process):
                state = poll_worker_process(
                    ProcessSandbox(process),
                    self.config(),
                    self.worker(),
                )
                self.assertIsNone(state)

        self.assertIs(
            poll_worker_process(
                ProcessSandbox(PollingProcess(response=ExecResponse(0, "exited"))),
                self.config(),
                self.worker(),
            ),
            False,
        )
        self.assertIs(
            poll_worker_process(
                ProcessSandbox(PollingProcess(response=ExecResponse(0, "running"))),
                self.config(),
                self.worker(),
            ),
            True,
        )

    def test_attach_rejects_reused_pid_for_both_platforms(self) -> None:
        expected_by_platform = {
            "linux": f"/home/daytona/.devin/remote/cache/devin-remote_{REMOTE_SHA}_linux_x64",
            "windows": rf"C:\ProgramData\devin-outposts\remote\{REMOTE_SHA}\devin-remote.exe",
        }
        for platform, expected in expected_by_platform.items():
            with self.subTest(platform=platform):
                process = PollingProcess(actual_executable="unrelated-process")
                attached = attach_worker_process(
                    ProcessSandbox(process),
                    self.config(),
                    SESSION_ID,
                    platform=platform,
                    remote_sha=REMOTE_SHA,
                )

                self.assertIsNone(attached)
                self.assertIn(expected, process.commands[0])

    def test_attach_keeps_transient_poll_state_retryable(self) -> None:
        attached = attach_worker_process(
            ProcessSandbox(PollingProcess(error=RuntimeError("temporary exec outage"))),
            self.config(),
            SESSION_ID,
            platform="linux",
            remote_sha=REMOTE_SHA,
        )

        self.assertIsNotNone(attached)
        self.assertEqual(attached.remote_sha, REMOTE_SHA)

    def test_supervisor_retries_unknown_poll_instead_of_declaring_worker_exit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            orchestrator = Orchestrator(
                make_config(Path(state_dir)), NullQueue(), object()
            )
            self.addCleanup(orchestrator._serve_executor.shutdown, wait=True)
            orchestrator.stop_event = ImmediateEvent()
            active = QueueEntry(session_id=SESSION_ID, session_status="running")
            suspended = QueueEntry(session_id=SESSION_ID, session_status="suspended")

            with (
                patch(
                    "devin_outposts.orchestrator.poll_worker_process",
                    side_effect=[None, True],
                ) as poll,
                patch.object(
                    orchestrator,
                    "_get_entry_or_none",
                    side_effect=[active, suspended],
                ),
            ):
                final_status = orchestrator.supervise(
                    SESSION_ID,
                    object(),
                    self.worker(),
                )

        self.assertEqual(final_status, "suspended")
        self.assertEqual(poll.call_count, 2)


if __name__ == "__main__":
    unittest.main()
