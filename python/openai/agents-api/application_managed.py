from __future__ import annotations

"""Application-managed: run an OpenAI Agents API session in a Daytona sandbox.

One process owns the whole session: it creates the session, starts a sandbox
running `codex exec-server`, submits a task, streams the result, and deletes the
sandbox and session when done. Best for short, interactive runs.
"""

import os
import shlex
from pathlib import Path

from daytona import (
    CreateSandboxFromImageParams,
    Daytona,
    Image,
    Sandbox,
    SessionExecuteRequest,
)
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

WORKSPACE = "/home/daytona/workspace"
EXEC_SESSION = "codex-exec-server"
BRIEF_FILE = Path(__file__).parent / "brief.txt"
TASK = "Read brief.txt and produce a five-step migration plan."


def build_image() -> Image:
    return Image.debian_slim("3.13").run_commands(
        "apt-get update && apt-get install -y --no-install-recommends "
        "ca-certificates curl file git nodejs npm poppler-utils ripgrep",
        "npm install --global @openai/codex@alpha",
    )


def start_sandbox(
    daytona: Daytona,
    executor_api_key: str,
    environment_id: str,
    remote_url: str,
) -> Sandbox:
    """Create a sandbox, seed the workspace, and start the executor inside it."""
    sandbox = daytona.create(
        CreateSandboxFromImageParams(
            image=build_image(),
            # Only the restricted executor key enters the sandbox. Agent-generated
            # code can read it, so it is a restricted environment key that can only
            # connect environments. The application key never leaves your machine.
            env_vars={"CODEX_API_KEY": executor_api_key},
            labels={"agents-api-environment-id": environment_id},
            # The executor's connection to OpenAI is an outbound, long-lived
            # WebSocket that Daytona's inactivity tracking does not observe.
            # Disable auto-stop so the sandbox is not stopped mid-turn; ttl_minutes
            # bounds its lifetime if a run is interrupted.
            auto_stop_interval=0,
            ttl_minutes=15,
        ),
        timeout=0,
    )

    try:
        # The sandbox user owns its home directory, so no permission setup is
        # needed for a workspace under it. Upload the task file from disk.
        sandbox.process.exec(f"mkdir -p {WORKSPACE}")
        sandbox.fs.upload_file(str(BRIEF_FILE), f"{WORKSPACE}/brief.txt")

        # Launch the executor with the environment ID and remote URL returned by
        # the API. Pass the remote URL through unchanged.
        command = shlex.join(
            [
                "codex",
                "exec-server",
                "--remote",
                remote_url,
                "--environment-id",
                environment_id,
            ]
        )
        sandbox.process.create_session(EXEC_SESSION)
        sandbox.process.execute_session_command(
            EXEC_SESSION,
            SessionExecuteRequest(
                command=f"cd {WORKSPACE} && exec {command}",
                run_async=True,
            ),
        )
        return sandbox
    except BaseException:
        sandbox.delete()
        raise


def main() -> None:
    # Application key: session and inference. Never enters the sandbox. Grant it
    # api.agents.read, api.agents.write, and api.responses.write.
    application_api_key = os.environ["OPENAI_API_KEY"]
    # Executor key: the only credential passed into the sandbox. Create it as a
    # restricted environment key on the Agents tab.
    executor_api_key = os.environ["OPENAI_EXECUTOR_API_KEY"]

    with OpenAI(api_key=application_api_key) as client:
        daytona = Daytona()

        session = client.beta.agents.sessions.create(
            agent={
                "model": "gpt-6-astra",
                "instructions": (
                    "Work from files in /home/daytona/workspace and answer concisely."
                ),
            },
            environment={"type": "self_hosted", "workspace_directory": WORKSPACE},
        )
        print(f"created session {session.id}")

        sandbox = None
        try:
            # Start the sandbox before submitting input. The turn waits for the
            # environment to connect, reported by agent.session.environment.connected.
            sandbox = start_sandbox(
                daytona,
                executor_api_key,
                session.environment.id,
                session.environment.remote_url,
            )
            print(f"started sandbox {sandbox.id}\n")

            # Subscribe to the event stream, then send input on the same session.
            with client.beta.agents.sessions.events.stream(session.id) as events:
                client.beta.agents.sessions.events.create(
                    session.id,
                    events=[
                        {
                            "type": "agent.session.input.message",
                            "input": [
                                {
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": TASK}],
                                }
                            ],
                        }
                    ],
                )
                for event in events:
                    if event.type == "agent.session.turn.output_text.delta":
                        print(event.delta, end="", flush=True)
                    elif event.type == "agent.session.environment.failed":
                        raise RuntimeError(f"environment failed: {event}")
                    elif event.type in (
                        "agent.session.turn.failed",
                        "agent.session.turn.cancelled",
                    ):
                        raise RuntimeError(event.type)
                    elif (
                        event.type == "agent.session.turn.completed"
                        and event.turn.subagent_id is None
                    ):
                        # Stop on the root agent's turn; ignore subagent turns.
                        break
            print()
        finally:
            # Delete the session while its environment is still connected, then
            # remove the sandbox. Both are server-side resources.
            client.beta.agents.sessions.delete(session.id)
            if sandbox is not None:
                sandbox.delete()


if __name__ == "__main__":
    main()
