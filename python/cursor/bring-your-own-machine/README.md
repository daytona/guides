# Cursor BYOM workers on Daytona

Run Cursor self-hosted workers in Daytona Linux sandboxes. A computer runs `agent worker controller` and the Python helper in this guide. That computer waits for Cursor requests, creates one sandbox per worker, and deletes each sandbox when its worker exits. Cursor keeps the agent loop and model access in its cloud. Commands, file changes, builds, and repository data stay in the sandbox.

The commands below use a POSIX shell. They work on macOS and Linux. Cursor BYOM can support other platforms, but this template has no Windows instructions.

## Prerequisites

- A computer that stays online while workers run.
- Python 3.12 or newer, with the `venv` module.
- A POSIX shell and `curl`.
- A Daytona account and [Daytona API key](https://www.daytona.io/docs/en/api-keys/).
- Daytona quota for one snapshot build and one sandbox per active worker. See [Daytona limits](https://www.daytona.io/docs/en/limits/).
- A Cursor Enterprise team and a Cursor service-account API key.
- A team-level Cursor GitHub App installation with access to each requested repository.
- Cursor team-administrator access to Cloud Agents settings.

Pool workers require an [Enterprise service-account key](https://cursor.com/docs/account/enterprise/service-accounts). A personal Cursor API key does not work.

## Install

Install the Cursor CLI on the computer that runs the controller:

```bash
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
agent --version
agent worker controller --help
```

`agent --version` must report `2026.08.25-3e8eec8`. `agent worker controller --help` must list `--spawn`.

Install this package from a clean `daytona-guides` clone:

```bash
cd python/cursor/bring-your-own-machine
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --editable .
command -v spawn-cursor-byom-worker
command -v build-cursor-byom-snapshot
```

Both installed commands must resolve inside the current `.venv`.

## Set up Cursor

A Cursor team administrator must complete these steps:

1. Open **Dashboard > Cloud Agents > Self-Hosted**.
2. Enable **Allow Self-Hosted Agents** for pool requests.
3. Enable Self-Hosted Pools for the team.
4. Enable GitHub token minting for self-hosted pool workers.
5. Give the Cursor GitHub App access to each requested repository.
6. Create or select the pool named `daytona`.

See [Cursor Self-Hosted Pools](https://cursor.com/docs/cloud-agent/bring-your-own-machine/pools) for current team settings and pool limits.

> **Note:** Linux CLI `2026.08.25-3e8eec8` lacks `--clone-git-repos`. The snapshot supplies `/usr/local/bin/clone-cursor-byom-repos` instead.

Do not put a GitHub personal access token in `.env`.

## Set the environment

Create the local environment file:

```bash
cp .env.example .env
```

Set the two keys and leave `SNAPSHOT_NAME` empty before the first build:

```dotenv
DAYTONA_API_KEY=replace-with-your-daytona-api-key
SNAPSHOT_NAME=
CURSOR_API_KEY=replace-with-your-cursor-service-account-key

```

Do not add `CURSOR_AGENT_WORKER_ID`, `CURSOR_POOL`, or `CURSOR_REQUEST_ID` to `.env`. Cursor supplies these values.

## Build the snapshot

The snapshot contains Linux, `git`, Cursor CLI `2026.08.25-3e8eec8`, and the executable clone hook. It contains no API keys.

Run the installed builder:

```bash
build-cursor-byom-snapshot
```

The command prints the snapshot name:

```json
{"reused":false,"snapshot_name":"cursor-byom-default-1234abcd","state":"active"}
```

Copy the printed `snapshot_name` into `.env`. The name above is only an example. See [Daytona snapshots](https://www.daytona.io/docs/en/snapshots/).

## Start the controller

From `python/cursor/bring-your-own-machine`, load `.env` and start the controller:

```bash
set -a; . ./.env; set +a
agent worker controller --spawn "$(pwd)/.venv/bin/spawn-cursor-byom-worker" --pool daytona
```

Keep this foreground process running. Do not run `spawn-cursor-byom-worker` directly during normal operation.

## Submit one request

1. Open [Cursor Agents](https://cursor.com/agents).
2. Create an agent for an HTTPS GitHub repository.
3. Select the self-hosted pool named `daytona`.
4. Submit the request while the controller runs.

The minted GitHub token does not authenticate an SSH remote.

## Code map

- `cursor_byom/config.py` parses environment values and builds sandbox names, labels, and the worker command.
- `cursor_byom/build_snapshot.py` builds or reuses the content-hash snapshot.
- `cursor_byom/spawn.py` replaces the sandbox, launches the worker, and starts cleanup.
- `cursor_byom/monitor.py` watches the worker process and deletes its sandbox.
- `cursor_byom/clone_repos.py` validates hook input and clones requested repositories.
- `cursor_byom/Dockerfile` installs the pinned Cursor CLI and `/usr/local/bin/clone-cursor-byom-repos`.

## Controller configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `DAYTONA_API_KEY` | Yes | Creates, finds, and deletes Daytona sandboxes. |
| `SNAPSHOT_NAME` | Yes after the build | Selects the active snapshot from the builder output. |
| `CURSOR_API_KEY` | Yes | Authenticates the controller and worker. Use an Enterprise service-account key. |
| `CURSOR_WORKER_IDLE_RELEASE_TIMEOUT` | No | Keeps a completed worker available for follow-up work. Default: `900` seconds. |
| `MONITOR_POLL_SECONDS` | No | Sets the monitor interval. Default: `5` seconds. |
| `SANDBOX_CREATE_TIMEOUT_SECONDS` | No | Sets the Daytona create and delete timeout. Default: `120` seconds. |
| `SANDBOX_LAUNCH_TIMEOUT_SECONDS` | No | Sets the worker launch timeout. Default: `60` seconds. |

## Runtime flow

1. A user submits a request to the `daytona` pool.
2. Cursor queues the request. The controller claims it and calls the installed spawn command.
3. The spawn command replaces the worker's deterministic sandbox and creates a fresh sandbox from `SNAPSHOT_NAME`.
4. The sandbox starts `/usr/local/bin/agent`. The session-start hook clones HTTPS repositories into `/home/daytona/workspace`.
5. The computer that runs the controller starts a monitor. The monitor deletes the sandbox after the worker exits.
6. If startup fails, the spawn command releases the claim, deletes the sandbox, and reports a redacted error.


If the monitor fails, Daytona auto-stop and delete-on-stop provide a fallback.

## Security and network

No inbound port is required. The worker management address `0.0.0.0:8080` stays inside the sandbox.

| Runs from | Outbound HTTPS destination |
| --- | --- |
| Computer running the controller | `cursor.com`, `downloads.cursor.com`, the configured Python package index, `api.cursor.com`, and `https://app.daytona.io/api` |
| Daytona sandbox | `api2.cursor.sh` or `api2direct.cursor.sh` |
| Daytona sandbox | `cloud-agent-artifacts.s3.us-east-1.amazonaws.com` for optional artifact uploads |
| Daytona sandbox | The requested HTTPS Git host and task-specific package or tool hosts |

The computer running the controller holds both API keys. The sandbox receives the Cursor service-account key, but not the Daytona key.

Cursor requires the key in the worker process. Agent tools and repository code run as the same OS user.

Untrusted agent code can inspect same-user process state and obtain the Cursor key. Use a dedicated, least-privilege service account for each customer.

Rotate the key after suspected exposure. Do not reuse sandboxes, service accounts, or Cursor keys across customers.

Cursor sends short-lived GitHub credentials to the claimed worker. This guide stores no GitHub token.

Cursor receives file chunks for inference and uploaded artifacts. Review [Cursor's security and network model](https://cursor.com/docs/cloud-agent/security-network).

## Validation checklist

1. Confirm `agent --version` reports `2026.08.25-3e8eec8`.
2. Build the snapshot and copy its exact name into `.env`.
3. Start the controller and submit one UI request to pool `daytona`.
4. Confirm Daytona shows labels `cursor.worker_id`, `cursor.request_id`, and `cursor.pool` on the new sandbox.
5. Confirm the HTTPS repository exists under `/home/daytona/workspace`.
6. Confirm the agent completes and the monitor deletes the sandbox.

Complete this checklist with an Enterprise team before production use.

## Troubleshooting

- **`agent` is not found or has the wrong version.** Export `PATH` again. Use `2026.08.25-3e8eec8` for both environments.

- **The controller rejects the Cursor key.** Confirm `CURSOR_API_KEY` is an Enterprise service-account key. Load `.env` again.

- **The spawn command reports missing claim values.** Start it through `agent worker controller`. Do not set claim values by hand.

- **The request stays queued.** Confirm the controller and request use pool `daytona`. Confirm **Allow Self-Hosted Agents** is enabled.

- **Repository clone fails.** Inspect `/tmp/cursor-byom/worker.log`. Confirm HTTPS access, token minting, and executable `/usr/local/bin/clone-cursor-byom-repos`.

- **Snapshot creation or worker launch fails.** Confirm `DAYTONA_API_KEY`, `SNAPSHOT_NAME`, the Daytona organization, and [Daytona limits](https://www.daytona.io/docs/en/limits/).

- **A sandbox remains after worker exit.** Confirm the computer retained Daytona access. Delete the sandbox only when no worker uses it.

- **A failed startup leaves a claimed request.** Use the [release-claim endpoint](https://cursor.com/docs/cloud-agent/api/endpoints#release-a-claim). Release only the failed request ID.
