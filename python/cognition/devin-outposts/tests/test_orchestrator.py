from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from devin_outposts.queue import DevinQueue, QueueEntry
from devin_outposts.config import Config
from devin_outposts.orchestrator import Orchestrator
from devin_outposts.worker import WorkerHandle, poll_worker_process, start_worker_process
from devin_outposts.queue_shapes import entry_platform
from devin_outposts.sandbox import sandbox_name_for

SESSION_ID = "devin-session-123"


class NotFoundError(Exception):
    status_code: int = 404


class ImmediateEvent(threading.Event):
    """Event whose waits return instantly so tests never sleep."""

    def wait(self, timeout: float | None = None) -> bool:
        return False


class AbsentEntryQueue(DevinQueue):
    """Queue whose entry has disappeared, as happens when a session suspends."""

    def __init__(self) -> None:
        super().__init__("https://example.test/api", "outposts-secret")

    def get(self, session_id: str) -> QueueEntry:
        raise NotFoundError(f"queue entry {session_id} not found")


class FakeSandbox:
    def __init__(self) -> None:
        self.state: str = "started"
        self.stopped: bool = False
        self.deleted: bool = False

    def stop(self, timeout: int | None = None) -> None:
        self.stopped = True
        self.state = "stopped"

    def delete(self, timeout: int | None = None) -> None:
        self.deleted = True
        self.state = "deleted"


class FakeDaytona:
    def __init__(self, sandboxes: dict[str, FakeSandbox]) -> None:
        self.sandboxes: dict[str, FakeSandbox] = sandboxes

    def get(self, name: str) -> FakeSandbox:
        try:
            return self.sandboxes[name]
        except KeyError:
            raise NotFoundError(name) from None


def make_config(state_dir: Path) -> Config:
    return Config(
        devin_outposts_token="outposts-secret",
        devin_api_url="https://example.test/api",
        outpost_id="outpost_env-outpost",
        snapshot_name="snapshot-name",
        max_concurrent_sessions=1,
        state_dir=state_dir,
        acceptor_id="acceptor-123",
        workdir="/home/daytona/workspace",
        devin_chrome_path="/usr/bin/chromium",
        repos=(),
        git_username=None,
        git_token=None,
        worker_poll_seconds=0.01,
    )


class AbsentQueueEntryTests(unittest.TestCase):
    """Suspended sessions leave the queue entirely, so an absent entry must be
    treated as "still suspended", never "terminated". Deleting the sandbox on
    an absent entry would destroy the disk state that resuming restores."""

    def make_orchestrator(self, sandbox: FakeSandbox) -> Orchestrator:
        state_dir = self.enterContext(tempfile.TemporaryDirectory())
        daytona = FakeDaytona({sandbox_name_for(SESSION_ID): sandbox})
        orchestrator = Orchestrator(make_config(Path(state_dir)), AbsentEntryQueue(), daytona)
        orchestrator.stop_event = ImmediateEvent()
        return orchestrator

    def test_supervise_stops_but_keeps_sandbox_when_entry_disappears(self) -> None:
        sandbox = FakeSandbox()
        orchestrator = self.make_orchestrator(sandbox)
        worker = WorkerHandle(
            sandbox_name=sandbox_name_for(SESSION_ID),
            pid="4242",
            pid_path="/tmp/worker.pid",
            log_path="/tmp/worker.log",
        )

        with patch("devin_outposts.orchestrator.poll_worker_process", return_value=True):
            final_status = orchestrator.supervise(SESSION_ID, sandbox, worker)
        self.assertEqual(final_status, "suspended")

        orchestrator._teardown_after_release(SESSION_ID, sandbox, final_status, worker_started=True)
        self.assertTrue(sandbox.stopped)
        self.assertFalse(sandbox.deleted)

    def test_wait_for_terminal_status_reports_absent_entry_as_suspended(self) -> None:
        orchestrator = self.make_orchestrator(FakeSandbox())
        self.assertEqual(orchestrator._wait_for_terminal_status(SESSION_ID), "suspended")

    def test_deleted_event_stops_sandbox_instead_of_deleting(self) -> None:
        sandbox = FakeSandbox()
        orchestrator = self.make_orchestrator(sandbox)

        event = {"type": "DELETED", "session_id": SESSION_ID, "cursor": "cursor-1"}
        orchestrator._handle_event(event, None)

        self.assertTrue(sandbox.stopped)
        self.assertFalse(sandbox.deleted)


class PendingListQueue(DevinQueue):
    """Queue that reports one pending entry via list, as the poller sees it."""

    def __init__(self, entry: QueueEntry) -> None:
        super().__init__("https://example.test/api", "outposts-secret")
        self.entry = entry
        self.list_phases: list[str | None] = []

    def list(self, outpost=None, phase=None, acceptor_id=None, cursor=None, first=200):  # type: ignore[override]
        self.list_phases.append(phase)
        from devin_outposts.queue import Page

        return Page(items=[self.entry])


class PendingPollTests(unittest.TestCase):
    """The pending poller bounds claim latency when the watch stream withholds
    events: each sweep must reconcile every pending entry it lists."""

    def test_poll_pending_once_reconciles_listed_entries(self) -> None:
        entry = QueueEntry(
            session_id=SESSION_ID,
            outpost_id="outpost_env-outpost",
            phase="pending",
            session_status="running",
            raw={},
        )
        state_dir = self.enterContext(tempfile.TemporaryDirectory())
        queue = PendingListQueue(entry)
        orchestrator = Orchestrator(make_config(Path(state_dir)), queue, FakeDaytona({}))
        orchestrator.stop_event = ImmediateEvent()

        reconciled: list[Any] = []
        with patch.object(orchestrator, "reconcile", side_effect=reconciled.append):
            orchestrator.poll_pending_once()

        self.assertEqual(queue.list_phases, ["pending"])
        self.assertEqual(len(reconciled), 1)
        self.assertIs(reconciled[0], entry)


class FakeExecResponse:
    def __init__(self, exit_code: int = 0, result: str = "") -> None:
        self.exit_code: int = exit_code
        self.result: str = result


class FakeWindowsProcess:
    def __init__(self, owner: "FakeWindowsSandbox") -> None:
        self.owner: FakeWindowsSandbox = owner

    def exec(self, command: str, timeout: int | None = None, env: Any = None) -> FakeExecResponse:
        self.owner.commands.append(command)
        decoded = ""
        if "-EncodedCommand" in command:
            decoded = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16le")
            self.owner.decoded_commands.append(decoded)
        if "Get-Process" in decoded:
            # Answer the worker poll from the presence of the fake PID file.
            alive = "C:/ProgramData/devin-outposts/sessions/devin-session-123/worker.pid" in self.owner.files
            return FakeExecResponse(0, "running" if alive else "exited")
        if "REMOTE_VERIFIED" in decoded:
            return FakeExecResponse(0, "REMOTE_VERIFIED")
        if "Start-Process" in decoded:
            # The detached bootstrap "runs": the PID file appears.
            self.owner.files["C:/ProgramData/devin-outposts/sessions/devin-session-123/worker.pid"] = b"4242\r\n"
        return FakeExecResponse(0, "")


class FakeWindowsFs:
    def __init__(self, owner: "FakeWindowsSandbox") -> None:
        self.owner: FakeWindowsSandbox = owner

    def upload_file(self, content: bytes | str, path: str, timeout: int | None = None) -> None:
        self.owner.uploads[path] = content if isinstance(content, bytes) else content.encode()

    def download_file(self, path: str) -> bytes:
        try:
            return self.owner.files[path]
        except KeyError:
            raise NotFoundError(path) from None


class FakeWindowsSandbox:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.decoded_commands: list[str] = []
        self.uploads: dict[str, bytes] = {}
        self.files: dict[str, bytes] = {}
        self.process: FakeWindowsProcess = FakeWindowsProcess(self)
        self.fs: FakeWindowsFs = FakeWindowsFs(self)


class WindowsWorkerLaunchTests(unittest.TestCase):
    def test_windows_launch_keeps_token_out_of_commands(self) -> None:
        sandbox = FakeWindowsSandbox()
        with tempfile.TemporaryDirectory() as state_dir:
            config = make_config(Path(state_dir))
        entry = QueueEntry(
            session_id=SESSION_ID,
            platform="windows",
            remote_binary_sha="c0ffee1234",
        )
        claim = {"status": {"gateway_url": "wss://gateway.test", "connect_token": "connect-secret"}}

        with (
            patch("devin_outposts.worker.fetch_remote_checksum", return_value="a" * 64) as checksum,
            patch("devin_outposts.worker_windows.time.sleep"),
        ):
            worker = start_worker_process(sandbox, config, SESSION_ID, entry, claim)

        self.assertEqual(worker.platform, "windows")
        self.assertEqual(worker.pid, "4242")
        checksum.assert_called_once_with("devin-remote_c0ffee1234_windows_x64.exe")

        # The connect token must reach the remote only through the uploaded
        # launch configuration, never through a command line.
        for command in self.assertedCommands(sandbox):
            self.assertNotIn("connect-secret", command)
        launch_config = json.loads(sandbox.uploads[
            r"C:\ProgramData\devin-outposts\sessions\devin-session-123\launch.json"
        ])
        self.assertEqual(launch_config["environment"]["DEVIN_OUTPOST_CONNECT_TOKEN"], "connect-secret")
        self.assertEqual(launch_config["environment"]["DEVIN_OUTPOST_SESSION_ID"], SESSION_ID)

        bootstrap = sandbox.uploads[
            r"C:\ProgramData\devin-outposts\sessions\devin-session-123\bootstrap.ps1"
        ].decode()
        self.assertIn("RedirectStandardInput", bootstrap)

        download = next(c for c in sandbox.decoded_commands if "REMOTE_VERIFIED" in c)
        self.assertIn("a" * 64, download)
        self.assertIn("Get-FileHash", download)

    def test_windows_poll_reads_pid_file_through_encoded_powershell(self) -> None:
        sandbox = FakeWindowsSandbox()
        with tempfile.TemporaryDirectory() as state_dir:
            config = make_config(Path(state_dir))
        worker = WorkerHandle(
            sandbox_name=SESSION_ID,
            pid="4242",
            pid_path="C:/ProgramData/devin-outposts/sessions/devin-session-123/worker.pid",
            log_path="C:/ProgramData/devin-outposts/sessions/devin-session-123/remote.log",
            platform="windows",
        )

        self.assertFalse(poll_worker_process(sandbox, config, worker))

        sandbox.files[worker.pid_path] = b"4242\r\n"
        self.assertTrue(poll_worker_process(sandbox, config, worker))

        decoded = sandbox.decoded_commands[-1]
        self.assertIn(worker.pid_path, decoded)
        self.assertIn("Get-Process", decoded)

    def assertedCommands(self, sandbox: FakeWindowsSandbox) -> list[str]:
        self.assertTrue(sandbox.commands)
        return sandbox.commands + sandbox.decoded_commands

    def test_entry_platform_defaults_to_linux(self) -> None:
        self.assertEqual(entry_platform(QueueEntry(session_id="x")), "linux")
        self.assertEqual(entry_platform({"platform": "Windows"}), "windows")
        self.assertEqual(entry_platform({"spec": {"platform": "windows"}}), "windows")


if __name__ == "__main__":
    unittest.main()
