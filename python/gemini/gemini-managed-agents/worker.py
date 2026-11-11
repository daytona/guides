# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Run one long-lived Gemini Managed Agents worker in a Daytona sandbox.

Creates a sandbox from the worker snapshot, starts
`gemini-api environments connect` inside it, and prints the worker's log until
you stop it with Ctrl-C. The worker leases the environment's interactions and
runs their tool calls in /workspace. The sandbox is deleted on exit.
"""

import os
import signal
import sys
import time

from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaError, DaytonaNotFoundError, Sandbox

import sandbox_lib

POLL_SECONDS = 2
RETRY_SECONDS = 10


def follow(sandbox: Sandbox, cmd_id: str) -> int:
    """Print the worker's log as it grows and return its exit code once it stops."""
    printed = 0
    while True:
        try:
            exit_code = sandbox_lib.worker_exit_code(sandbox, cmd_id)
            log = sandbox_lib.worker_log(sandbox, cmd_id)
        except DaytonaNotFoundError:
            raise
        except DaytonaError as e:
            # The worker keeps running in the sandbox; only reading its log failed. Retry rather
            # than end this script, which would delete the sandbox and its files.
            print(f"!! reading the worker log failed, retrying in {RETRY_SECONDS}s: {e}", file=sys.stderr, flush=True)
            time.sleep(RETRY_SECONDS)
            continue
        print(log[printed:], end="", flush=True)
        printed = len(log)
        if exit_code is not None:
            return exit_code
        time.sleep(POLL_SECONDS)


def raise_keyboard_interrupt(_signum, _frame) -> None:
    raise KeyboardInterrupt


def main() -> int:
    sandbox_lib.load_env()
    environment_id = os.environ["GEMINI_ENVIRONMENT_ID"]
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)

    daytona = Daytona()
    sandbox = daytona.create(
        CreateSandboxFromSnapshotParams(
            snapshot=sandbox_lib.snapshot_name(),
            # The worker authenticates with the environment-scoped key, never with GEMINI_API_KEY.
            env_vars={"GEMINI_ENVIRONMENT_KEY": os.environ["GEMINI_ENVIRONMENT_KEY"]},
            labels={sandbox_lib.ENVIRONMENT_ID_LABEL: environment_id, sandbox_lib.MODE_LABEL: "connect"},
            # Reading the worker log below counts as sandbox activity. If this script dies, the
            # sandbox stops after 15 idle minutes and, because it is ephemeral, is deleted.
            auto_stop_interval=15,
            ephemeral=True,
        ),
        timeout=180,
    )
    print(f"sandbox {sandbox.id} is up; connecting a worker to environment {environment_id}", flush=True)
    exit_code = 0
    try:
        exit_code = follow(sandbox, sandbox_lib.start_worker(sandbox, "connect"))
        print(f"worker exited with code {exit_code}")
    except KeyboardInterrupt:
        print("\nstopping the worker")
    finally:
        sandbox.delete()
        print(f"deleted sandbox {sandbox.id}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
