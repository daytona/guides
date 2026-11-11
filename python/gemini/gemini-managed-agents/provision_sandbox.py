# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Provision a fresh Daytona sandbox for one leased Gemini Managed Agents interaction.

`gemini-api environments poll` runs this script once per leased interaction:

    gemini-api environments poll --provision-cmd ".venv/bin/python provision_sandbox.py"

It reads the poller's v1 JSON payload from stdin, creates an ephemeral sandbox,
starts `gemini-api environments serve` in it with the interaction's short-lived
lease token, and exits once the worker has attached. A detached copy of this
script (`--watch`) then waits for the worker to finish, appends the worker's
log to logs/<interaction_id>.log, and deletes the sandbox.

The sandbox never receives your Gemini API key or the environment key.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaError, DaytonaNotFoundError, Sandbox

import sandbox_lib

LOG_DIR = sandbox_lib.HERE / "logs"
# The poller kills this script after --provision-timeout (2 minutes by default),
# so sandbox creation plus the attach wait must fit well inside it.
CREATE_TIMEOUT_SECONDS = 60
ATTACH_TIMEOUT_SECONDS = 45
# How long the worker must stay up after attaching before the lease is handed off.
ATTACH_GRACE_SECONDS = 3
WATCH_INTERVAL_SECONDS = 15
# Tries at reading the finished worker's log before deleting the sandbox without it.
LOG_READ_ATTEMPTS = 4
# Hard upper bound on one interaction's sandbox, even if its worker never exits.
SANDBOX_TTL_MINUTES = 120


def log(interaction_id: str, message: str) -> None:
    """Append to logs/<interaction_id>.log. The poller discards this script's stdout."""
    LOG_DIR.mkdir(exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", interaction_id)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(LOG_DIR / f"{name}.log", "a", encoding="utf-8") as f:
        f.write(f"{stamp} {message}\n")


def wait_for_attach(sandbox: Sandbox, cmd_id: str) -> bool:
    """Wait for `serve` to attach to the interaction, then make sure it did not fail right away."""
    deadline = time.monotonic() + ATTACH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if sandbox_lib.worker_exit_code(sandbox, cmd_id) is not None:
            return False
        if "Attached interaction session" in sandbox_lib.worker_log(sandbox, cmd_id):
            time.sleep(ATTACH_GRACE_SECONDS)
            return sandbox_lib.worker_exit_code(sandbox, cmd_id) in (None, 0)
        time.sleep(0.5)
    return False


def provision(payload: dict[str, Any]) -> int:
    if payload.get("schema_version") != "v1":
        print(f"unsupported provision payload schema {payload.get('schema_version')!r}", file=sys.stderr)
        return 1
    interaction_id = payload["interaction_id"]
    environment_id = payload["environment_id"]
    # Set with `create_environment.py --snapshot NAME`; the Gemini API passes it through unchanged.
    custom_config = (payload.get("environment_config") or {}).get("custom_config") or {}
    custom_snapshot = (custom_config.get("daytona") or {}).get("snapshot")
    snapshot = custom_snapshot or sandbox_lib.snapshot_name()

    daytona = Daytona()
    sandbox = daytona.create(
        CreateSandboxFromSnapshotParams(
            snapshot=snapshot,
            labels={
                sandbox_lib.ENVIRONMENT_ID_LABEL: environment_id,
                sandbox_lib.INTERACTION_ID_LABEL: interaction_id,
                sandbox_lib.MODE_LABEL: "serve",
            },
            # The watcher's polling counts as sandbox activity. If the watcher dies, the sandbox
            # stops after 15 idle minutes and, because it is ephemeral, is deleted.
            auto_stop_interval=15,
            ephemeral=True,
            ttl_minutes=SANDBOX_TTL_MINUTES,
        ),
        timeout=CREATE_TIMEOUT_SECONDS,
    )
    source = "custom_config" if custom_snapshot else "default"
    log(interaction_id, f"created sandbox {sandbox.id} from {source} snapshot {snapshot}")

    args = ["serve", "--interaction-id", interaction_id, "--lease-token", payload["lease_token"]]
    if payload.get("server_url"):
        args += ["--server-url", payload["server_url"]]
    try:
        cmd_id = sandbox_lib.start_worker(sandbox, *args)
        attached = wait_for_attach(sandbox, cmd_id)
    except Exception:
        sandbox.delete()
        raise

    if not attached:
        output = sandbox_lib.worker_log(sandbox, cmd_id)
        log(interaction_id, f"worker failed to attach; deleting sandbox {sandbox.id}\n{output}")
        print(f"worker in sandbox {sandbox.id} failed to attach:\n{output}", file=sys.stderr)
        sandbox.delete()
        return 1

    # Once this script exits, the poller stops heartbeating the lease and the worker's own
    # stream keeps it alive. The detached watcher outlives this process and cleans up.
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--watch", sandbox.id, cmd_id, interaction_id],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log(interaction_id, f"worker attached in sandbox {sandbox.id}; handed off")
    return 0


def watch(sandbox_id: str, cmd_id: str, interaction_id: str) -> int:
    """Wait for the worker to exit, save its log, and delete the sandbox."""
    daytona = Daytona()
    log_read_failures = 0
    while True:
        try:
            sandbox = daytona.get(sandbox_id)
            # Toolbox calls like this one count as activity, so the sandbox is not
            # auto-stopped while the interaction runs.
            exit_code = sandbox_lib.worker_exit_code(sandbox, cmd_id)
        except DaytonaNotFoundError:
            log(interaction_id, f"sandbox {sandbox_id} no longer exists")
            return 0
        except DaytonaError as e:
            log(interaction_id, f"checking the worker failed, retrying: {e}")
            time.sleep(WATCH_INTERVAL_SECONDS)
            continue

        if exit_code is not None:
            try:
                output = sandbox_lib.worker_log(sandbox, cmd_id)
            except DaytonaError as e:
                # Deleting the sandbox loses the log for good, so retry a transient error first.
                log_read_failures += 1
                if log_read_failures < LOG_READ_ATTEMPTS:
                    log(interaction_id, f"reading the worker log failed, retrying: {e}")
                    time.sleep(WATCH_INTERVAL_SECONDS)
                    continue
                output = f"(reading the worker log failed {LOG_READ_ATTEMPTS} times: {e})"
            log(interaction_id, f"worker exited with code {exit_code}; worker log:\n{output}")
            try:
                sandbox.delete()
            except DaytonaError as e:
                log(interaction_id, f"deleting sandbox {sandbox_id} failed: {e}; it auto-stops and is deleted later")
                return 1
            log(interaction_id, f"deleted sandbox {sandbox_id}")
            return 0
        time.sleep(WATCH_INTERVAL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a Daytona sandbox for one leased interaction.")
    parser.add_argument(
        "--watch", nargs=3, metavar=("SANDBOX_ID", "COMMAND_ID", "INTERACTION_ID"), help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    sandbox_lib.load_env()
    if args.watch:
        return watch(*args.watch)
    return provision(json.load(sys.stdin))


if __name__ == "__main__":
    raise SystemExit(main())
