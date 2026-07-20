"""Reconcile queue state with sandbox and worker lifecycle actions.

pending -> claim and serve; claimed by this acceptor -> reattach; suspended ->
release and stop while retaining the sandbox; terminated -> release and delete.
An entry absent while serving is treated as suspended, never terminated, because
suspension is only transiently visible in the queue.
"""

from __future__ import annotations

import inspect
import logging
import os
import posixpath
import shlex
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import Config, ConfigError, atomic_write_text
from .queue import Conflict, DevinQueue, QueueEntry
from .queue_shapes import (
    entry_acceptor_id,
    entry_phase,
    entry_platform,
    entry_outpost_id,
    entry_session_id,
    entry_session_status,
    event_cursor,
    event_entry,
    event_is_deleted,
    event_session_id,
    require_session_id,
    unpack_page,
)
from .sandbox import (
    is_not_found,
    labels_for,
    sandbox_label,
    sandbox_name_for,
    sandbox_state,
)
from .worker import (
    WorkerHandle,
    attach_worker_process,
    poll_worker_process,
    start_worker_process,
)
from .worker_windows import powershell_encoded, ps_quote

try:  # Daytona is an install-time dependency; imports stay here for clear failures.
    from daytona import CreateSandboxFromSnapshotParams, Daytona, ListSandboxesQuery
except ImportError:  # pragma: no cover - exercised only in an uninstalled environment.
    CreateSandboxFromSnapshotParams = None  # type: ignore[assignment]
    Daytona = None  # type: ignore[assignment]
    ListSandboxesQuery = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)
ACTIVE_SESSION_STATUSES = {"pending", "running"}
TERMINAL_SESSION_STATUSES = {"suspended", "terminated"}


class StateStore:
    # --- startup & reattach ---

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.cursor_path = state_dir / "watch_cursor"
        self._lock = threading.Lock()

    def read_cursor(self) -> str | None:
        try:
            value = self.cursor_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return value or None

    def write_cursor(self, cursor: str | None) -> None:
        if not cursor:
            return
        with self._lock:
            atomic_write_text(self.cursor_path, cursor + "\n")


class Orchestrator:
    def __init__(self, config: Config, queue: DevinQueue, daytona: Any):
        self.config = config
        self.queue = queue
        self.daytona = daytona
        self.state = StateStore(config.state_dir)
        self.semaphore = threading.Semaphore(config.max_concurrent_sessions)
        self.stop_event = threading.Event()
        self._serve_executor = ThreadPoolExecutor(
            max_workers=config.max_concurrent_sessions,
            thread_name_prefix="devin-outposts-worker",
        )
        self._active: dict[str, Future[None]] = {}
        self._active_lock = threading.Lock()

    def run(self) -> None:
        LOGGER.info(
            "Starting orchestrator for outpost %s as acceptor %s",
            self.config.outpost_id,
            self.config.acceptor_id,
        )
        try:
            self._start_janitor()
            self._start_pending_poller()
            self._reattach_claimed_sessions()
            initial_cursor = self._initial_reconcile()
            watch_cursor = self.state.read_cursor() or initial_cursor
            self._watch_forever(watch_cursor)
        finally:
            self.stop_event.set()
            self._serve_executor.shutdown(wait=True)

    def _start_janitor(self) -> None:
        thread = threading.Thread(
            target=self._janitor_loop, name="devin-outposts-janitor", daemon=True
        )
        thread.start()

    def _start_pending_poller(self) -> None:
        # The watch stream is the primary signal, but it has been observed to
        # withhold events while staying open (beta, 2026-07-20). This poller
        # bounds claim latency so a pending session is never stuck waiting for
        # the five-minute stream cycle; Devin gives up on a session whose
        # machine takes that long to arrive.
        thread = threading.Thread(
            target=self._pending_poll_loop,
            name="devin-outposts-pending-poll",
            daemon=True,
        )
        thread.start()

    def _pending_poll_loop(self) -> None:
        while not self.stop_event.wait(self.config.pending_poll_seconds):
            try:
                self.poll_pending_once()
            except Exception as exc:
                LOGGER.warning("Pending poll failed: %s", self.config.redacted(exc))

    def poll_pending_once(self) -> None:
        entries, _ = self._list_all_entries(phase="pending")
        for entry in entries:
            self.reconcile(entry)

    def _reattach_claimed_sessions(self) -> None:
        entries, _ = self._list_all_entries(
            phase="claimed", acceptor_id=self.config.acceptor_id
        )
        for entry in entries:
            self.reconcile(entry, already_claimed=True)

    def _initial_reconcile(self) -> str | None:
        entries, cursor = self._list_all_entries()
        for entry in entries:
            self.reconcile(entry)
        return cursor

    # --- watch loop ---

    def _watch_forever(self, cursor: str | None) -> None:
        while not self.stop_event.is_set():
            try:
                for event in self.queue.watch(self.config.outpost_id, cursor=cursor):
                    if self.stop_event.is_set():
                        break
                    cursor = self._handle_event(event, cursor)
                cursor = self._reconcile_after_watch_gap(cursor)
            except KeyboardInterrupt:
                self.stop_event.set()
                raise
            except (
                Exception
            ) as exc:  # Watch streams are expected to reconnect periodically.
                LOGGER.warning("Watch disconnected: %s", self.config.redacted(exc))
                cursor = self._reconcile_after_watch_gap(cursor)
                self.stop_event.wait(self.config.watch_reconnect_seconds)

    def _reconcile_after_watch_gap(self, previous_cursor: str | None) -> str | None:
        try:
            cursor = self._initial_reconcile() or previous_cursor
            self.state.write_cursor(cursor)
            return cursor
        except Exception as exc:
            LOGGER.warning(
                "Full reconcile after watch gap failed: %s", self.config.redacted(exc)
            )
            return previous_cursor

    def _handle_event(self, event: Any, previous_cursor: str | None) -> str | None:
        cursor = event_cursor(event) or previous_cursor
        if event_is_deleted(event):
            session_id = event_session_id(event)
            if session_id:
                # Suspended sessions leave the queue entirely, so entry deletion is
                # not proof of termination. Keep the disk; reconcile deletes the
                # sandbox only on an observed "terminated" status.
                self._stop_sandbox_if_inactive(session_id)
            self.state.write_cursor(cursor)
            return cursor

        entry = event_entry(event)
        if entry is None:
            LOGGER.debug("Skipping queue event without an entry")
            self.state.write_cursor(cursor)
            return cursor

        self.reconcile(entry)
        self.state.write_cursor(cursor)
        return cursor

    # --- reconcile ---

    def reconcile(self, entry: QueueEntry, *, already_claimed: bool = False) -> None:
        session_id = entry_session_id(entry)
        if not session_id:
            LOGGER.warning("Skipping queue entry without session_id")
            return

        if entry_outpost_id(entry) and entry_outpost_id(entry) != self.config.outpost_id:
            return

        phase = entry_phase(entry)
        status = entry_session_status(entry)
        acceptor_id = entry_acceptor_id(entry)

        if already_claimed or (
            phase == "claimed" and acceptor_id == self.config.acceptor_id
        ):
            self._spawn_serve(entry, already_claimed=True)
            return

        if phase == "pending" and status in ACTIVE_SESSION_STATUSES:
            self._spawn_serve(entry, already_claimed=False)
            return

        if status == "suspended":
            self._stop_sandbox_if_inactive(session_id)
            return

        if status == "terminated":
            self._delete_sandbox_if_inactive(session_id)

    # --- serve & supervise ---

    def _spawn_serve(self, entry: QueueEntry, *, already_claimed: bool) -> None:
        session_id = entry_session_id(entry)
        if not session_id:
            return

        with self._active_lock:
            future = self._active.get(session_id)
            if future and not future.done():
                return

            future = self._serve_executor.submit(
                self._serve_wrapper, entry, already_claimed
            )
            self._active[session_id] = future

    def _serve_wrapper(self, entry: QueueEntry, already_claimed: bool) -> None:
        session_id = entry_session_id(entry) or "unknown"
        try:
            self.serve(entry, already_claimed=already_claimed)
        except Exception as exc:
            LOGGER.error(
                "Serve failed for %s: %s", session_id, self.config.redacted(exc)
            )
        finally:
            with self._active_lock:
                self._active.pop(session_id, None)

    def serve(self, entry: QueueEntry, *, already_claimed: bool = False) -> None:
        session_id = require_session_id(entry)
        sandbox: Any | None = None
        worker: WorkerHandle | None = None
        claimed = False
        final_status: str | None = None

        with self.semaphore:
            try:
                if already_claimed:
                    claimed = True
                    sandbox, _ = self.ensure_sandbox(
                        session_id, create_if_missing=False
                    )
                    if sandbox is None:
                        LOGGER.warning(
                            "Claimed session %s has no sandbox; releasing", session_id
                        )
                        return
                    worker = attach_worker_process(
                        sandbox,
                        self.config,
                        session_id,
                        platform=entry_platform(entry),
                        remote_sha=str(getattr(entry, "remote_binary_sha", "") or ""),
                    )
                    if worker is None:
                        latest = self._safe_get_entry(session_id)
                        final_status = (
                            entry_session_status(latest)
                            if latest is not None
                            else "suspended"
                        )
                        LOGGER.warning(
                            "Claimed session %s has no live worker; releasing",
                            session_id,
                        )
                        return
                    LOGGER.info(
                        "Reattached session %s to sandbox %s",
                        session_id,
                        worker.sandbox_name,
                    )
                else:
                    latest = self._safe_get_entry(session_id) or entry
                    if (
                        entry_phase(latest) != "pending"
                        or entry_session_status(latest) not in ACTIVE_SESSION_STATUSES
                    ):
                        LOGGER.info(
                            "Skipping session %s because it is no longer pending/runnable",
                            session_id,
                        )
                        return

                    try:
                        claim = self.queue.claim(session_id, self.config.acceptor_id)
                    except Conflict:
                        LOGGER.info("Claim lost for session %s", session_id)
                        return
                    claimed = True

                    sandbox, _ = self.ensure_sandbox(session_id, create_if_missing=True)
                    if sandbox is None:
                        raise RuntimeError(
                            f"sandbox could not be created for {session_id}"
                        )
                    self.clone_configured_repos(sandbox, entry_platform(latest))
                    worker = start_worker_process(
                        sandbox, self.config, session_id, latest, claim
                    )
                    LOGGER.info(
                        "Serving session %s in sandbox %s",
                        session_id,
                        worker.sandbox_name,
                    )

                final_status = self.supervise(session_id, sandbox, worker)
            finally:
                if claimed:
                    self._release_claim(session_id)
                if sandbox is not None:
                    self._teardown_after_release(
                        session_id,
                        sandbox,
                        final_status,
                        worker_started=worker is not None,
                    )

    def supervise(
        self, session_id: str, sandbox: Any, worker: WorkerHandle
    ) -> str | None:
        last_status: str | None = None
        while not self.stop_event.wait(self.config.worker_poll_seconds):
            worker_alive = poll_worker_process(sandbox, self.config, worker)
            try:
                entry = self._get_entry_or_none(session_id)
            except Exception as exc:
                LOGGER.warning(
                    "Queue get failed for %s during supervision: %s",
                    session_id,
                    self.config.redacted(exc),
                )
                continue
            if entry is None:
                # Suspended sessions leave the queue entirely, so an absent entry
                # means "still suspended", never "terminated". Terminated sessions
                # report a terminal status before their entry disappears.
                LOGGER.info(
                    "Queue entry disappeared for session %s; treating as suspended",
                    session_id,
                )
                return "suspended"

            last_status = entry_session_status(entry)
            if last_status in TERMINAL_SESSION_STATUSES:
                LOGGER.info("Session %s reached %s", session_id, last_status)
                return last_status

            if worker_alive is False:
                LOGGER.warning(
                    "Worker exited before terminal queue status for session %s",
                    session_id,
                )
                return self._wait_for_terminal_status(session_id) or "worker_exited"

        return last_status

    def ensure_sandbox(
        self, session_id: str, *, create_if_missing: bool
    ) -> tuple[Any | None, bool]:
        sandbox_name = sandbox_name_for(session_id)
        labels = labels_for(self.config, session_id)
        try:
            sandbox = self.daytona.get(sandbox_name)
            self._validate_sandbox_labels(sandbox, labels)
            self._ensure_started(sandbox)
            return sandbox, False
        except Exception as exc:
            if not is_not_found(exc):
                raise
            if not create_if_missing:
                return None, False

        if CreateSandboxFromSnapshotParams is None:
            raise RuntimeError("Daytona SDK is not installed")

        params = CreateSandboxFromSnapshotParams(
            name=sandbox_name,
            snapshot=self.config.snapshot_name,
            labels=labels,
            auto_stop_interval=0,
            auto_delete_interval=-1,
        )
        sandbox = self.daytona.create(params, timeout=120)
        self._ensure_started(sandbox)
        LOGGER.info("Created sandbox %s for session %s", sandbox_name, session_id)
        return sandbox, True

    def clone_configured_repos(self, sandbox: Any, platform: str) -> None:
        if not self.config.repos:
            return

        if platform == "windows":
            repos_dir = self.config.windows_workdir
            mkdir_command = powershell_encoded(
                f"New-Item -ItemType Directory -Path {ps_quote(repos_dir)} -Force | Out-Null"
            )
        else:
            repos_dir = self.config.workdir
            mkdir_command = f"mkdir -p {shlex.quote(repos_dir)}"
        mkdir_response = sandbox.process.exec(mkdir_command, timeout=30)
        if getattr(mkdir_response, "exit_code", 1) != 0:
            raise RuntimeError("failed to create sandbox repos dir")

        for repo in self.config.repos:
            if platform == "windows":
                target_path = rf"{repos_dir}\{repo.target_name}"
                exists_command = powershell_encoded(
                    f"if (Test-Path -LiteralPath {ps_quote(target_path)}) {{ exit 0 }}; exit 1"
                )
            else:
                target_path = posixpath.join(repos_dir, repo.target_name)
                exists_command = f"test -e {shlex.quote(target_path)}"
            exists_response = sandbox.process.exec(exists_command, timeout=15)
            if getattr(exists_response, "exit_code", 1) == 0:
                LOGGER.info(
                    "Configured repo %s already exists in sandbox; skipping clone",
                    repo.target_name,
                )
                continue
            LOGGER.info("Cloning configured repo %s into sandbox", repo.target_name)
            try:
                sandbox.git.clone(
                    url=repo.url,
                    path=target_path,
                    username=self.config.git_username,
                    password=self.config.git_token,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"failed to clone configured repo {repo.target_name}: "
                    f"{self.config.redacted(exc)}"
                ) from exc

    def _release_claim(self, session_id: str) -> None:
        try:
            self.queue.release(session_id, self.config.acceptor_id)
            LOGGER.info("Released session %s", session_id)
        except Conflict:
            LOGGER.info(
                "Release conflict for session %s; claim is no longer held", session_id
            )
        except Exception as exc:
            if is_not_found(exc):
                return
            LOGGER.warning(
                "Release failed for %s: %s", session_id, self.config.redacted(exc)
            )

    def _teardown_after_release(
        self,
        session_id: str,
        sandbox: Any,
        final_status: str | None,
        *,
        worker_started: bool,
    ) -> None:
        if final_status == "terminated":
            self._delete_sandbox(sandbox, session_id)
            return
        if final_status == "suspended":
            self._stop_sandbox(sandbox, session_id)
            return
        if not worker_started or final_status not in ACTIVE_SESSION_STATUSES:
            self._stop_sandbox(sandbox, session_id)

    def _wait_for_terminal_status(self, session_id: str) -> str | None:
        for _ in range(5):
            if self.stop_event.wait(3.0):
                return None
            try:
                entry = self._get_entry_or_none(session_id)
            except Exception as exc:
                LOGGER.warning(
                    "Queue get failed for %s while waiting for terminal status: %s",
                    session_id,
                    self.config.redacted(exc),
                )
                continue
            if entry is None:
                return "suspended"
            status = entry_session_status(entry)
            if status in TERMINAL_SESSION_STATUSES:
                return status
        return None

    # --- queue access ---

    def _list_all_entries(
        self,
        *,
        phase: str | None = None,
        acceptor_id: str | None = None,
    ) -> tuple[list[QueueEntry], str | None]:
        entries: list[QueueEntry] = []
        cursor: str | None = None
        last_cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = self.queue.list(
                self.config.outpost_id,
                phase=phase,
                acceptor_id=acceptor_id,
                cursor=cursor,
            )
            page_entries, next_cursor, has_next = unpack_page(page)
            entries.extend(page_entries)
            last_cursor = next_cursor or last_cursor
            if not has_next or not next_cursor:
                return entries, last_cursor
            if next_cursor in seen_cursors:
                raise RuntimeError("queue pagination cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def _get_entry_or_none(self, session_id: str) -> QueueEntry | None:
        try:
            return self.queue.get(session_id)
        except Exception as exc:
            if is_not_found(exc):
                return None
            raise

    def _safe_get_entry(self, session_id: str) -> QueueEntry | None:
        try:
            return self._get_entry_or_none(session_id)
        except Exception as exc:
            LOGGER.warning(
                "Queue get failed for %s: %s", session_id, self.config.redacted(exc)
            )
            return None

    # --- sandbox lifecycle ---

    def _ensure_started(self, sandbox: Any) -> None:
        state = sandbox_state(sandbox)
        if state in {"", "started", "running"}:
            return
        sandbox.start(timeout=120)

    def _validate_sandbox_labels(self, sandbox: Any, labels: Mapping[str, str]) -> None:
        current = dict(getattr(sandbox, "labels", None) or {})
        if any(current.get(key) != value for key, value in labels.items()):
            raise RuntimeError(
                "sandbox labels do not match the requested Devin session and outpost"
            )

    def _stop_sandbox_if_inactive(self, session_id: str) -> None:
        if self._is_active(session_id):
            return
        sandbox = self._get_sandbox_by_session_id(session_id)
        if sandbox is not None:
            self._stop_sandbox(sandbox, session_id)

    def _delete_sandbox_if_inactive(self, session_id: str) -> None:
        if self._is_active(session_id):
            return
        sandbox = self._get_sandbox_by_session_id(session_id)
        if sandbox is not None:
            self._delete_sandbox(sandbox, session_id)

    def _get_sandbox_by_session_id(self, session_id: str) -> Any | None:
        try:
            return self.daytona.get(sandbox_name_for(session_id))
        except Exception as exc:
            if is_not_found(exc):
                return None
            LOGGER.warning(
                "Sandbox lookup failed for %s: %s",
                session_id,
                self.config.redacted(exc),
            )
            return None

    def _stop_sandbox(self, sandbox: Any, session_id: str) -> None:
        try:
            if sandbox_state(sandbox) not in {
                "stopped",
                "archived",
                "destroyed",
                "deleted",
            }:
                sandbox.stop(timeout=120)
            LOGGER.info("Stopped sandbox for session %s", session_id)
        except Exception as exc:
            if is_not_found(exc):
                return
            LOGGER.warning(
                "Sandbox stop failed for %s: %s", session_id, self.config.redacted(exc)
            )

    def _delete_sandbox(self, sandbox: Any, session_id: str) -> None:
        try:
            sandbox.delete(timeout=120)
            LOGGER.info("Deleted sandbox for session %s", session_id)
        except Exception as exc:
            if is_not_found(exc):
                return
            LOGGER.warning(
                "Sandbox delete failed for %s: %s",
                session_id,
                self.config.redacted(exc),
            )

    def _is_active(self, session_id: str) -> bool:
        with self._active_lock:
            future = self._active.get(session_id)
            return bool(future and not future.done())

    def _active_session_ids(self) -> set[str]:
        with self._active_lock:
            return {
                session_id
                for session_id, future in self._active.items()
                if not future.done()
            }

    # --- janitor ---

    def _janitor_loop(self) -> None:
        while not self.stop_event.wait(self.config.janitor_interval_seconds):
            try:
                self.run_janitor_once()
            except Exception as exc:
                LOGGER.warning("Janitor failed: %s", self.config.redacted(exc))

    def run_janitor_once(self) -> None:
        if ListSandboxesQuery is None:
            return
        query = ListSandboxesQuery(labels={"devin.outpost_id": self.config.outpost_id})
        active = self._active_session_ids()
        for sandbox in self.daytona.list(query):
            session_id = sandbox_label(sandbox, "devin.session_id")
            if not session_id or session_id in active:
                continue
            try:
                entry = self._get_entry_or_none(session_id)
            except Exception as exc:
                LOGGER.warning(
                    "Janitor queue lookup failed for %s: %s",
                    session_id,
                    self.config.redacted(exc),
                )
                continue
            status = entry_session_status(entry) if entry is not None else None
            if entry is None or status == "suspended":
                self._stop_sandbox(sandbox, session_id)
            elif status == "terminated":
                self._delete_sandbox(sandbox, session_id)


def build_queue(config: Config) -> DevinQueue:
    try:
        params = inspect.signature(DevinQueue).parameters
    except (TypeError, ValueError):
        params = {}

    kwargs: dict[str, str] = {}
    if "api_url" in params:
        kwargs["api_url"] = config.devin_api_url
    elif "base_url" in params:
        kwargs["base_url"] = config.devin_api_url
    elif "devin_api_url" in params:
        kwargs["devin_api_url"] = config.devin_api_url

    if "token" in params:
        kwargs["token"] = config.devin_outposts_token
    elif "devin_outposts_token" in params:
        kwargs["devin_outposts_token"] = config.devin_outposts_token

    if kwargs:
        return DevinQueue(**kwargs)
    return DevinQueue(config.devin_api_url, config.devin_outposts_token)


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # Reserved for a future CLI without changing the entrypoint.
    configure_logging()
    try:
        config = Config.from_env()
        if Daytona is None:
            raise ConfigError("Daytona SDK is not installed")
        queue = build_queue(config)
        orchestrator = Orchestrator(config=config, queue=queue, daytona=Daytona())
        orchestrator.run()
    except KeyboardInterrupt:
        LOGGER.info("Stopping orchestrator")
        return 130
    except ConfigError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
