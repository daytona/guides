from __future__ import annotations

"""Webhook-managed: provision Daytona sandboxes for Agents API sessions on demand.

Deploy this as a public HTTPS endpoint and register the URL as an OpenAI webhook,
subscribing to `agent.session.action_required`, `agent.session.idle`, and
`agent.session.failed`. When a session needs its environment connected, OpenAI
calls this handler; it starts or reconnects the session's Daytona sandbox and
(re)launches the executor. When the session goes idle it stops the sandbox to
release compute, and on failure it deletes the sandbox.

Stopping on idle is what saves compute between turns: the next input raises an
`environment_connection` action, the webhook fires, and the handler wakes the
sandbox. Daytona's stop/start preserves the sandbox filesystem across turns.

The handler is intentionally single-process and minimal. For production, add a
durable work queue, idempotent and retried provisioning, and an idle grace period
before stopping. See OpenAI's webhook-managed guidance:
https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle

Run it with: uvicorn webhook_managed:app --host 0.0.0.0 --port 8000
Extra dependencies: fastapi, uvicorn, openai
"""

import hashlib
import json
import os
import shlex

from daytona import (
    AsyncDaytona,
    CreateSandboxFromImageParams,
    DaytonaNotFoundError,
    Image,
    SessionExecuteRequest,
)
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from openai import AsyncOpenAI, InvalidWebhookSignatureError, OpenAI

load_dotenv()

WORKSPACE = "/home/daytona/workspace"
EXEC_SESSION = "codex-exec-server"

app = FastAPI()


def sandbox_name(session_id: str) -> str:
    """Deterministic name so a session always maps to the same sandbox."""
    return f"agents-api-{hashlib.sha256(session_id.encode()).hexdigest()[:24]}"


def build_image() -> Image:
    return Image.debian_slim("3.13").run_commands(
        "apt-get update && apt-get install -y --no-install-recommends "
        "ca-certificates curl file git nodejs npm poppler-utils ripgrep",
        "npm install --global @openai/codex@alpha",
    )


async def connect_worker(
    daytona: AsyncDaytona, session_id: str, environment_id: str, remote_url: str
) -> None:
    """Start or reconnect the session's sandbox and (re)launch the executor.

    A retried delivery reuses the same named sandbox, and `flock` prevents a
    duplicate executor. Concurrent deliveries can still race the sandbox
    get/create; serialize those with the durable work queue noted above.
    """
    name = sandbox_name(session_id)
    try:
        sandbox = await daytona.get(name)
    except DaytonaNotFoundError:
        sandbox = None

    if sandbox is None:
        sandbox = await daytona.create(
            CreateSandboxFromImageParams(
                name=name,
                image=build_image(),
                # Only the restricted executor key enters the sandbox.
                env_vars={"CODEX_API_KEY": os.environ["OPENAI_EXECUTOR_API_KEY"]},
                labels={"agents-api-session-id": session_id},
                auto_stop_interval=0,
                # ttl_minutes caps an abandoned sandbox's lifetime. Raise or renew
                # it for sessions that stay active longer, so a later reconnect
                # does not find the sandbox expired and lose the workspace.
                ttl_minutes=30,
            ),
            timeout=0,
        )
    elif sandbox.state != "started":
        # Stopped between turns: bring it back. The filesystem is preserved.
        await sandbox.start()

    await sandbox.process.exec(f"mkdir -p {WORKSPACE}")
    try:
        await sandbox.process.get_session(EXEC_SESSION)
    except DaytonaNotFoundError:
        await sandbox.process.create_session(EXEC_SESSION)
    # Launch the executor with the environment ID and remote URL from the session.
    # Reuse the remote URL unchanged, including on reconnect. `flock --nonblock`
    # makes provisioning idempotent: a retried or concurrent webhook cannot start
    # a second executor while one is already running.
    command = shlex.join(
        [
            "flock",
            "--nonblock",
            "/tmp/codex-exec-server.lock",
            "codex",
            "exec-server",
            "--remote",
            remote_url,
            "--environment-id",
            environment_id,
        ]
    )
    await sandbox.process.execute_session_command(
        EXEC_SESSION,
        SessionExecuteRequest(
            command=f"cd {WORKSPACE} && exec {command}",
            run_async=True,
        ),
    )


async def delete_worker(daytona: AsyncDaytona, session_id: str) -> None:
    try:
        await daytona.delete(await daytona.get(sandbox_name(session_id)))
    except DaytonaNotFoundError:
        pass


async def stop_worker(daytona: AsyncDaytona, session_id: str) -> None:
    """Stop the session's sandbox to release compute; the filesystem is preserved."""
    try:
        sandbox = await daytona.get(sandbox_name(session_id))
    except DaytonaNotFoundError:
        return
    if sandbox.state == "started":
        await sandbox.stop()


async def reconcile(session_id: str) -> None:
    """Fetch the session, then provision or release its sandbox accordingly.

    The webhook carries no environment details, so retrieve the session to read
    its status, environment, and required actions.
    """
    async with (
        AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]) as client,
        AsyncDaytona() as daytona,
    ):
        session = await client.beta.agents.sessions.retrieve(session_id)
        if session.environment.type != "self_hosted":
            return
        if session.status == "failed":
            await delete_worker(daytona, session_id)
            return
        # Provision only while an environment_connection action is present.
        # Other actions (function_call) belong to your application's tool handler.
        action = next(
            (a for a in session.required_actions if a.type == "environment_connection"),
            None,
        )
        if action is None:
            return
        await connect_worker(
            daytona,
            session_id,
            session.environment.id,
            session.environment.remote_url,
        )


@app.post("/webhooks/openai")
async def webhook(request: Request) -> Response:
    body = await request.body()
    client = OpenAI(webhook_secret=os.environ["OPENAI_WEBHOOK_SECRET"])
    try:
        client.webhooks.verify_signature(payload=body, headers=request.headers)
    except (InvalidWebhookSignatureError, ValueError):
        return Response(status_code=400)

    event = json.loads(body)
    event_type = event["type"]
    session_id = event["data"]["id"]

    if event_type == "agent.session.failed" or (
        event_type == "agent.session.action_required"
        and event["data"]["required_action"]["type"] == "environment_connection"
    ):
        await reconcile(session_id)
    elif event_type == "agent.session.idle":
        # Release compute between turns; the next input reconnects the sandbox.
        async with AsyncDaytona() as daytona:
            await stop_worker(daytona, session_id)

    return Response(status_code=200)
