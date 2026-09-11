# OpenAI Agents API with Daytona

## Overview

This example runs an [OpenAI Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview) session in a Daytona sandbox. OpenAI hosts the agent (the Codex harness, which plans, calls tools, and manages the session); Daytona provides the sandbox where the agent runs commands, edits files, and produces artifacts.

The sandbox runs `codex exec-server`, which opens an outbound connection to OpenAI and registers as the session's execution environment. No inbound ports are exposed. Your application creates the session, connects the sandbox, sends input, and streams the result.

## Features

- **OpenAI-hosted harness, your sandbox:** OpenAI runs orchestration, context management, and recovery; the agent's code runs in an isolated Daytona sandbox you control.
- **Least-privilege credentials:** Two keys. The broader application key never enters the sandbox; only a restricted executor key does.
- **Bring your own image:** Install any tools, languages, or dependencies the agent needs into the sandbox image.
- **Automatic cleanup:** The sandbox and session are deleted when the run finishes.

## Prerequisites

- **Python:** Version 3.11 or higher is required.
- **OpenAI project with Agents API access** (public beta).

## Environment Variables

The Agents API uses two OpenAI keys so the credential exposed to sandbox code is minimal:

- `OPENAI_API_KEY` — **application key.** Creates and streams sessions and runs model inference. Stays on your machine. Grant it `api.agents.read`, `api.agents.write`, and `api.responses.write`.
- `OPENAI_EXECUTOR_API_KEY` — **executor key.** The only credential passed into the sandbox, where agent-generated code can read it. Create it as a restricted **environment key** with `api.agents.environments.connect`; set every other permission to **None**.
- `DAYTONA_API_KEY` — access to Daytona sandboxes. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- `OPENAI_WEBHOOK_SECRET` — **webhook-managed example only.** The signing secret for your OpenAI webhook endpoint; `webhook_managed.py` uses it to verify that deliveries came from OpenAI.

Create the application key from the [OpenAI Developer Platform](https://platform.openai.com/api-keys) and the executor key on the [Agents tab](https://platform.openai.com/agents?tab=environments&environment_view=keys), both for the same organization, project, and user or service account that owns the session. Copy `.env.example` to `.env` and fill in the values.

> Note: the application key needs `api.agents.write` for session operations and `api.responses.write` for model inference.

## Getting Started

### Install dependencies

```bash
pip install openai daytona python-dotenv
```

The webhook-managed example additionally needs FastAPI and Uvicorn:

```bash
pip install fastapi uvicorn
```

### Run the example

```bash
python application_managed.py
```

The program creates a session, starts a Daytona sandbox running the executor, submits a task, streams the agent's answer, and deletes the sandbox and session when done.

### Files

- `application_managed.py` — the runnable end-to-end example (start here).
- `webhook_managed.py` — the `connect_worker` / `delete_worker` helpers for the webhook-managed pattern (see below).
- `brief.txt` — the task the agent reads inside the sandbox; uploaded from disk into the workspace.

## How It Works

1. **Create the session.** `client.beta.agents.sessions.create(...)` with `environment.type = "self_hosted"` returns an environment ID and a session-specific `remote_url`.
2. **Start the sandbox.** A sandbox is created from a Debian image with Node.js and the Codex CLI. The restricted executor key is injected as `CODEX_API_KEY`; the local `brief.txt` is uploaded into the workspace.
3. **Launch the executor.** `codex exec-server --remote <remote_url> --environment-id <id>` runs in a background process session. It dials out to OpenAI (HTTPS to `api.openai.com`, WebSocket to `codex-cloud-environments.chatgpt.com`) and registers as the environment.
4. **Send input and stream.** The turn waits for the environment to connect (reported by `agent.session.environment.connected`), then the agent reads the brief and streams its plan back.
5. **Clean up.** The session and sandbox are deleted in a `finally` block.

### Why `auto_stop_interval=0`

The executor's connection to OpenAI is an outbound, long-lived WebSocket that Daytona's inactivity tracking does not observe, so a running-but-quiet sandbox looks idle. Disabling auto-stop prevents the sandbox from being stopped mid-turn; `ttl_minutes` bounds its lifetime if a run is interrupted. To release compute between turns instead, see the webhook-managed pattern below.

### Faster connect with a snapshot

Building the image on first use keeps this example self-contained. For regular use, bake Codex and ripgrep into a [Daytona snapshot](https://www.daytona.io/docs/en/snapshots/) so the sandbox connects sooner.

## Application-managed vs webhook-managed

This example is **application-managed**: one process owns the whole session and keeps the sandbox up for its duration. That is the simplest shape and the right one for short, interactive runs.

For long-running or many-session workloads, use the **webhook-managed** pattern: stop the sandbox when the session goes idle to save compute, and start or reconnect it on the next turn. When new input arrives for a disconnected environment, OpenAI emits an `agent.session.action_required` (`environment_connection`) webhook; a handler starts or resumes the sandbox and relaunches the executor with the same environment ID and remote URL. Daytona's stop/start preserves the sandbox filesystem across turns.

`webhook_managed.py` in this directory implements the core of that handler — `connect_worker(...)` (create-or-wake the sandbox by label, then relaunch the executor), `stop_worker(...)` (stop the sandbox on `agent.session.idle` to release compute), and `delete_worker(...)` — so you can wire it into your own webhook endpoint. It subscribes to `agent.session.action_required`, `agent.session.idle`, and `agent.session.failed`. See OpenAI's [Daytona provider guide](https://developers.openai.com/api/docs/guides/agents-api/environments/providers/daytona) and [environment lifecycle](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle) for the full webhook-managed flow.

## A note on Daytona Secrets

Some Daytona guides inject the OpenAI key with [Daytona Secrets](https://www.daytona.io/docs/en/secrets/), which keep the raw value out of the sandbox and substitute it into outbound HTTPS request headers. That works for tools that call `https://api.openai.com` directly. It is **not** currently suitable for the Agents API executor: the executor's data plane is a WebSocket to `codex-cloud-environments.chatgpt.com`, and Secret substitution on that upgraded connection is not yet supported. Pass the executor key as an environment variable, and keep it least-privilege (`api.agents.environments.connect`) so its exposure to sandbox code is harmless.
