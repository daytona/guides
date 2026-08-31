# Cursor BYOM workers on Daytona

Run Cursor Self-Hosted Pool workers in Daytona `container`, `linux-vm`, or `windows` sandboxes. A macOS or Linux computer runs `agent worker controller` and the Python helper in this guide. The controller claims Cursor requests, creates one sandbox for each worker, and deletes the sandbox when the worker exits.

Cursor keeps the agent loop and model access in its cloud. Commands, file changes, builds, and repository data stay in the Daytona sandbox.

| Daytona class | Guest OS | Default snapshot source | Workspace |
| --- | --- | --- | --- |
| `container` | Linux | The included Dockerfile | `/home/daytona/workspace` |
| `linux-vm` | Linux | `daytona-vm-medium` | `/home/daytona/workspace` |
| `windows` | Windows | `windows-medium` | `C:\cursor\workspace` |

The controller commands below need a POSIX shell. The Windows support is for the Daytona guest, not for the controller computer.

## Prerequisites

- A macOS or Linux computer that stays online while workers run.
- Python 3.12 or newer, with the `venv` module.
- A POSIX shell and `curl`.
- A Daytona account and [Daytona API key](https://www.daytona.io/docs/en/api-keys/).
- A Daytona target that supports the selected sandbox class.
- Daytona quota for one snapshot build and one sandbox for each active worker. See [Daytona limits](https://www.daytona.io/docs/en/limits/).
- A Cursor Enterprise team and a Cursor service-account API key.
- A team-level Cursor GitHub App installation with access to each requested repository.
- Cursor team-administrator access to Cloud Agents settings.

Pool workers require an [Enterprise service-account key](https://cursor.com/docs/account/enterprise/service-accounts). A personal Cursor API key cannot start a pool worker.

The `linux-vm` and `windows` builders also need their source snapshots in the selected Daytona target. You can select a different source with `--source-snapshot`.

## Install

Install the lab channel of the Cursor CLI on the computer that runs the controller. The stable channel does not include `agent worker controller`.

```bash
curl 'https://cursor.com/install?channel=lab' -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
```

If the Cursor CLI is already installed, select the lab channel and install its current release:

```bash
agent set-channel lab
agent update
```

Verify the installed release and the controller command:

```bash
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

Both commands must resolve inside the current `.venv`.

## Set up Cursor

A Cursor team administrator must complete these steps:

1. Open **Dashboard > Cloud Agents > Self-Hosted**.
2. Enable **Allow Self-Hosted Agents**.
3. Enable Self-Hosted Pools for the team.
4. Enable GitHub token minting for self-hosted pool workers.
5. Give the Cursor GitHub App access to each requested repository.
6. Create one pool for each sandbox class that you plan to run.

For example, use `daytona-container`, `daytona-linux-vm`, and `daytona-windows`. See [Cursor Self-Hosted Pools](https://cursor.com/docs/cloud-agent/self-hosted-guides/pool) for current team settings and limits.

The pinned Cursor CLI does not have `--clone-git-repos`. Each snapshot includes a class-specific session-start hook instead.

Do not put a GitHub personal access token in `.env`.

## Set the environment

Create the local environment file:

```bash
cp .env.example .env
```

Set the keys and the Daytona target. Leave `SNAPSHOT_NAME` empty before the first build:

```dotenv
DAYTONA_API_KEY=replace-with-your-daytona-api-key
DAYTONA_TARGET=us
SNAPSHOT_NAME=
CURSOR_API_KEY=replace-with-your-cursor-service-account-key
```

Use a target that supports the class that you will build. Do not add `CURSOR_AGENT_WORKER_ID`, `CURSOR_POOL`, or `CURSOR_REQUEST_ID`. Cursor supplies these claim values.

## Build a snapshot

The builder creates or reuses a content-addressed snapshot. It stores no API keys. Select one class and target:

```bash
# Linux container
build-cursor-byom-snapshot --sandbox-class container --target us

# Linux VM
build-cursor-byom-snapshot \
  --sandbox-class linux-vm \
  --target eu-central-1

# Windows
build-cursor-byom-snapshot --sandbox-class windows --target us
```

The targets above are examples. Class availability depends on the Daytona organization.

The container build uses `cursor_byom/Dockerfile`. A VM build creates a temporary sandbox from the source snapshot, provisions it inside the guest, stops it, and captures a cold snapshot. Every VM build or reuse then boots a fresh verifier. A failed verifier causes deletion of the uncertified snapshot.

The command prints JSON:

```json
{"reused":false,"sandbox_class":"windows","snapshot_name":"cursor-byom-windows-1234abcd","state":"active","target":"us"}
```

Copy the exact `snapshot_name` into `.env`. The name above is only an example. Keep `DAYTONA_TARGET` set to the target that owns the snapshot. See [Daytona snapshots](https://www.daytona.io/docs/en/snapshots/).

Use `--name` only when you need a stable explicit name. The default name changes when any pinned recipe input changes. Use `--source-snapshot` to replace `daytona-vm-medium` or `windows-medium`.

## Start a controller

Load the environment and start one controller for the selected snapshot:

```bash
set -a; . ./.env; set +a
agent worker controller \
  --spawn "$(pwd)/.venv/bin/spawn-cursor-byom-worker" \
  --pool daytona-windows
```

Keep this foreground process running. Do not run `spawn-cursor-byom-worker` directly during normal operation.

One controller configuration selects one snapshot and one Daytona target. Run a separate controller, environment, snapshot, and Cursor pool for each sandbox class. The spawn helper reads the class from the snapshot metadata. Do not set a separate sandbox-class environment variable.

## Submit one request

1. Open [Cursor Agents](https://cursor.com/agents).
2. Create an agent for an HTTPS GitHub repository.
3. Select the pool for the required Daytona class.
4. Submit the request while that pool's controller runs.

The minted GitHub token does not authenticate an SSH remote.

## Runtime flow

1. A user submits a request to a Cursor pool.
2. The controller claims the request and calls the installed spawn command.
3. The spawn command reads the snapshot class and creates a fresh sandbox from `SNAPSHOT_NAME`.
4. A Linux sandbox starts `/usr/local/bin/agent`. A Windows sandbox starts the pinned `node.exe` and Cursor agent entry point.
5. The session-start hook clones the requested HTTPS repositories into the class workspace.
6. The controller computer starts a monitor. Linux monitoring reads `/proc`. Windows monitoring checks the exact Node process path.
7. The monitor deletes the sandbox after the worker exits.
8. If startup fails, the spawn command releases the claim, deletes the sandbox, and reports a redacted error.

If the monitor fails, Daytona auto-stop and delete-on-stop provide a fallback.

## Code map

- `cursor_byom/build_snapshot.py` selects the class builder.
- `cursor_byom/build_linux_vm_snapshot.py` provisions, captures, and verifies Linux VM snapshots.
- `cursor_byom/build_windows_snapshot.py` provisions, captures, and verifies Windows snapshots.
- `cursor_byom/config.py` parses controller values and builds worker commands and labels.
- `cursor_byom/spawn.py` creates the sandbox, launches the worker, and starts cleanup.
- `cursor_byom/worker_windows.py` starts and inspects the native Windows worker.
- `cursor_byom/monitor.py` deletes the sandbox when its worker exits.
- `cursor_byom/clone_repos.py` handles Linux session-start cloning.
- `cursor_byom/clone_repos_windows.ps1` handles Windows session-start cloning.

## Controller configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `DAYTONA_API_KEY` | Yes | Creates, finds, and deletes Daytona sandboxes. |
| `DAYTONA_TARGET` | Recommended | Selects the Daytona target that owns the snapshot. |
| `SNAPSHOT_NAME` | Yes after the build | Selects the active snapshot from the builder output. |
| `CURSOR_API_KEY` | Yes | Authenticates the controller and worker. Use an Enterprise service-account key. |
| `CURSOR_WORKER_IDLE_RELEASE_TIMEOUT` | No | Keeps a completed worker available for follow-up work. Default: `900` seconds. |
| `MONITOR_POLL_SECONDS` | No | Sets the monitor interval. Default: `5` seconds. |
| `SANDBOX_CREATE_TIMEOUT_SECONDS` | No | Sets the Daytona create and delete timeout. Default: `120` seconds. |
| `SANDBOX_LAUNCH_TIMEOUT_SECONDS` | No | Sets the worker launch timeout. Default: `60` seconds. |

## Security and network

No inbound port is required. The worker management address `0.0.0.0:8080` stays inside the sandbox.

| Runs from | Outbound HTTPS destination |
| --- | --- |
| Controller computer | `cursor.com`, `downloads.cursor.com`, the configured Python package index, `api.cursor.com`, and `https://app.daytona.io/api` |
| Daytona sandbox | `api2.cursor.sh` or `api2direct.cursor.sh` |
| Daytona sandbox | `cloud-agent-artifacts.s3.us-east-1.amazonaws.com` for optional artifact uploads |
| Daytona sandbox | The requested HTTPS Git host and task-specific package or tool hosts |

The controller computer holds both API keys. The sandbox receives the Cursor service-account key, but not the Daytona key. On Windows, the launcher removes its transient environment file after the worker starts.

Cursor requires the key in the worker process. Agent tools and repository code run as the same OS user. Untrusted code can inspect same-user process state and obtain the Cursor key.

Use a dedicated, least-privilege service account for each customer. Rotate the key after suspected exposure. Do not reuse sandboxes, service accounts, or Cursor keys across customers.

Cursor sends short-lived GitHub credentials to the claimed worker. This guide stores no GitHub token. Cursor receives file chunks for inference and uploaded artifacts. Review [Cursor's security and network model](https://cursor.com/docs/cloud-agent/security-network).

The clone hooks accept only credential-free HTTPS repository URLs. They reject URL user information, query strings, and fragments before Git can store them in repository metadata.

## Validation

Run the deterministic checks:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tests/live_e2e.py --help
```

The live verifier spends real Daytona and Cursor credits. It creates an agent and sandbox, asks Cursor to write an exact marker, checks the native worker process, stops that process, verifies monitor cleanup, and deletes the Cursor agent.

The default `machine` mode needs a personal Cursor user key. It uses Cursor My Machines so that any Cloud Agents account can verify the snapshot:

```bash
set -a; . ./.env; set +a
.venv/bin/python tests/live_e2e.py \
  --sandbox-class linux-vm \
  --target eu-central-1 \
  --snapshot "$SNAPSHOT_NAME"
```

Personal My Machines proves real Cursor execution in the selected snapshot. It does not prove the Enterprise pool claim path.

Use an Enterprise service-account key to test the complete controller and claim path:

```bash
.venv/bin/python tests/live_e2e.py \
  --sandbox-class windows \
  --target us \
  --snapshot "$SNAPSHOT_NAME" \
  --cursor-mode team-pool
```

Run the live command once for each class and its matching target.

## Troubleshooting

- **`agent` is not found or has the wrong version.** Export `PATH` again. Select the lab channel and run `agent update`. Use `2026.08.25-3e8eec8` on the controller and in every snapshot.
- **The controller rejects the Cursor key.** Confirm `CURSOR_API_KEY` is an Enterprise service-account key. Load `.env` again.
- **The spawn command reports missing claim values.** Start it through `agent worker controller`. Do not set claim values by hand.
- **The request stays queued.** Confirm the controller and request use the same pool. Confirm **Allow Self-Hosted Agents** is enabled.
- **Daytona cannot find the snapshot.** Confirm `DAYTONA_TARGET` matches the target used for the build.
- **A VM build cannot find its source snapshot.** Select a source in the same target with `--source-snapshot`.
- **Linux repository cloning fails.** Inspect `/tmp/cursor-byom/worker.log`. Confirm HTTPS access and the executable clone hook.
- **Windows repository cloning fails.** Inspect `C:\ProgramData\cursor-byom\worker.stderr.log`. Confirm HTTPS access, Git installation, and the PowerShell clone hook.
- **A sandbox remains after worker exit.** Confirm the controller computer retained Daytona access. Delete the sandbox only when no worker uses it.
- **A failed startup leaves a claimed request.** Use the [release-claim endpoint](https://cursor.com/docs/cloud-agent/api/endpoints#release-a-claim). Release only the failed request ID.
