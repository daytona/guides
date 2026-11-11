# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""Helpers shared by the snapshot builder and both worker modes."""

from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path

import dotenv
from daytona import Sandbox, SessionExecuteRequest

HERE = Path(__file__).resolve().parent
DOCKERFILE = HERE / "Dockerfile"

# Root for the agent's file tools and working directory for its shell commands.
WORKSPACE = "/workspace"
# Daytona session that runs the gemini-api worker process.
SESSION_ID = "gemini-worker"

ENVIRONMENT_ID_LABEL = "gemini.environment_id"
INTERACTION_ID_LABEL = "gemini.interaction_id"
MODE_LABEL = "gemini.mode"


def load_env() -> None:
    """Load .env from this directory, whichever directory the script is started from."""
    dotenv.load_dotenv(HERE / ".env", override=True)


def snapshot_name() -> str:
    """Name the snapshot after the Dockerfile's hash, so editing the Dockerfile builds a new one."""
    override = os.environ.get("SNAPSHOT_NAME")
    if override:
        return override
    digest = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:8]
    return f"gemini-managed-agents-{digest}"


def start_worker(sandbox: Sandbox, *args: str) -> str:
    """Start `gemini-api environments <args>` in the background and return its command id."""
    command = shlex.join(["gemini-api", "environments", *args, "--root-dir", WORKSPACE, "--workdir", WORKSPACE])
    sandbox.process.create_session(SESSION_ID)
    response = sandbox.process.execute_session_command(
        SESSION_ID, SessionExecuteRequest(command=command, run_async=True)
    )
    return response.cmd_id


def worker_log(sandbox: Sandbox, cmd_id: str) -> str:
    """Return everything the worker has logged so far."""
    return sandbox.process.get_session_command_logs(SESSION_ID, cmd_id).output or ""


def worker_exit_code(sandbox: Sandbox, cmd_id: str) -> int | None:
    """Return the worker's exit code, or None while it is still running."""
    return sandbox.process.get_session_command(SESSION_ID, cmd_id).exit_code
