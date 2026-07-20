# Devin Outposts on Daytona

Run Devin Outposts sessions on Daytona sandboxes, Linux or Windows. A user runs the orchestrator on a machine they control. The orchestrator watches a Devin Outposts queue, claims sessions for one outpost, creates or resumes a Daytona sandbox for each session, launches the pinned `devin-remote` binary inside that sandbox, then releases and stops or deletes the sandbox when the session sleeps or ends.

## Prerequisites

- Devin Enterprise with Outposts enabled.
- A Daytona account and API key that can create snapshots and manage sandboxes.
- Python 3.12 on the machine that runs the orchestrator.
- A Devin organization administrator who can manage enterprise settings and service users.
- Linux or Windows worker sandboxes. Each outpost serves one platform; run one orchestrator process per outpost.

Install the package:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

`outposts-connect` fills in the Devin settings. Add your Daytona API key and
snapshot name to `.env` before running commands that call Daytona.

## Connect Devin

Run the connection command on the same machine as your browser:

```bash
outposts-connect --platform linux
```

The command opens Devin's connection page. A Devin organization administrator
confirms the outpost name and platform and clicks **Connect**. Devin redirects the
browser to a temporary listener on `http://localhost:8765/callback`; the command
exchanges that one-time code directly with Devin and writes
`DEVIN_OUTPOSTS_TOKEN`, `DEVIN_API_URL`, and `OUTPOST_ID` to this project's `.env`.
The listener then exits. The machine token does not pass through the browser,
and nothing is written to a global environment store.

For a Windows outpost, the flow is identical:

```bash
outposts-connect --platform windows
```

To serve Linux and Windows outposts at the same time, run one orchestrator per
outpost, each from its own checkout with its own `.env`.

The command and browser must run on the same machine because the callback uses
`localhost`. For a headless or remote orchestrator host, run the connection on a
workstation and transfer `.env` securely, or use manual setup. See Cognition's
[Outposts partner integration documentation](https://docs.devin.ai/cloud/outposts/partners)
for the authorization flow.

## Token scopes

| Token | Scope | Used for |
|---|---|---|
| `DEVIN_OUTPOSTS_TOKEN` | `account.outposts.machine` | Created with a service user by `outposts-connect`; used for queue list, watch, claim, and release. Sandboxes never receive this token; each remote gets its claim's connect token. |
| `DAYTONA_API_KEY` | Daytona API access | Snapshot creation and sandbox lifecycle calls. |
| `GIT_TOKEN` | Repo-read access, only if `REPOS` needs it | Optional repo pre-clone step. |

`DEVIN_OUTPOSTS_TOKEN` is intentionally named after Devin's Outposts
machine-serving contract. Do not treat it as interchangeable with a generic
`DEVIN_API_TOKEN` from unrelated Devin API scripts.

## Manual outpost setup

If the connection flow is unavailable, install the Devin CLI and create one
outpost per platform with an outpost-create token:

| Token | Scope | Used for |
|---|---|---|
| Devin outpost-create token | `account.outposts.orchestrator` | One-time outpost creation with `devin worker outpost create`. Remove it from your shell after the outpost exists. |

```bash
export DEVIN_API_URL="https://api.devin.ai"
export DEVIN_OUTPOST_CREATE_TOKEN="replace-with-outpost-create-token"

devin worker outpost create daytona-linux \
  --platform linux \
  --description "Daytona Linux sandboxes for Devin Outposts" \
  --api-url "$DEVIN_API_URL" \
  --token "$DEVIN_OUTPOST_CREATE_TOKEN"
```

For Windows sandboxes, create a separate outpost with `--platform windows` and run
a second orchestrator instance against it.

Do not add `/opbeta` to `DEVIN_API_URL`; the queue client appends that path.
Copy the returned outpost ID into `OUTPOST_ID` in `.env`, and set
`DEVIN_OUTPOSTS_TOKEN` to a service-user key with the
`account.outposts.machine` scope.

## Build the Linux snapshot

The snapshot builder uses `devin_outposts/Dockerfile.default` and the Daytona SDK. It adds the GitHub CLI and the directories the Devin remote expects on top of Daytona's standard sandbox image, and prints the Dockerfile hash prefix plus the snapshot name. If `SNAPSHOT_NAME` is set before the build, the builder uses that value. Otherwise it derives `devin-outposts-default-{sha8}` from `devin_outposts/Dockerfile.default`.

The snapshot bakes in 2 vCPU, 8 GiB memory, and 10 GiB disk per sandbox, and each concurrently served session runs one sandbox. If sandbox creation fails with a quota error, check your organization's [Daytona tier limits](https://www.daytona.io/docs/en/limits/) and lower `MAX_CONCURRENT_SESSIONS` or the resource defaults in the builder to fit.

```bash
set -a
. ./.env
set +a

build-devin-outposts-snapshot
```

If you have not installed the package, run this instead:

```bash
python -m devin_outposts.build_linux_snapshot
```

Copy the printed snapshot name into `SNAPSHOT_NAME` in `.env` before starting the orchestrator.

## Build the Windows snapshot

Windows outposts use `devin_outposts/build_windows_snapshot.py` with `devin_outposts/provision_windows.ps1`. The
provisioner installs pinned Git for Windows, Chrome for Testing, and the Devin
CLI, then verifies them plus ffmpeg and Daytona Computer Use on a fresh sandbox
created from the snapshot. The snapshot name derives from the provisioner hash
as `devin-outposts-windows-{sha8}`.

```bash
build-devin-outposts-windows-snapshot
```

If you have not installed the package, run this instead:

```bash
python -m devin_outposts.build_windows_snapshot
```

The builder starts from the Daytona `windows-medium` snapshot by default; pass
`--source-snapshot` to override. Copy the printed snapshot name into
`SNAPSHOT_NAME` in the `.env` used by the Windows outpost's orchestrator instance.

## Run the orchestrator

After `.env` has `DEVIN_OUTPOSTS_TOKEN`, `DEVIN_API_URL`, `DAYTONA_API_KEY`, `OUTPOST_ID`, and `SNAPSHOT_NAME`, start the orchestrator:

```bash
set -a
. ./.env
set +a

devin-outposts-orchestrator
```

If you have not installed the package, run this instead:

```bash
python -m devin_outposts.orchestrator
```

Create Devin sessions from the Devin UI or Slack and select the outpost you created. The orchestrator will claim matching sessions from that outpost.

## Code map

- `devin_outposts.config` — defines the environment contract for orchestration.
- `devin_outposts.connect` — authorizes an outpost through Devin and writes its machine credentials to `.env`.
- `devin_outposts.queue` — provides the thin typed client for the early-access queue API.
- `devin_outposts.queue_shapes` — normalizes drifting beta queue payload shapes.
- `devin_outposts.sandbox` — identifies and inspects sandboxes across restarts.
- `devin_outposts.worker` — dispatches worker lifecycle operations by platform.
- `devin_outposts.worker_linux` — launches the pinned, verified Linux remote.
- `devin_outposts.worker_windows` — launches the remote under Windows sandbox constraints.
- `devin_outposts.orchestrator` — reconciles queue state with sandbox and worker lifecycle.
- `devin_outposts.build_linux_snapshot` — builds the hash-named Linux snapshot.
- `devin_outposts.build_windows_snapshot` — builds the hash-named Windows snapshot.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the component and lifecycle design.

## Configuration

| Variable | Required | Notes |
|---|---:|---|
| `DEVIN_OUTPOSTS_TOKEN` | Yes | Service-user key scoped for machine serving, `account.outposts.machine`. The orchestrator sends it as a bearer token to the queue API. Sandboxes never receive it; each remote gets only its claim's connect token. |
| `DEVIN_API_URL` | Yes | Devin API base without `/opbeta`. Default public base is `https://api.devin.ai`. |
| `DAYTONA_API_KEY` | Yes | Used by the Daytona SDK for snapshot creation and sandbox lifecycle operations. |
| `OUTPOST_ID` | Yes | The outpost ID written by `outposts-connect` or returned by manual outpost creation. Run one orchestrator process per outpost. |
| `SNAPSHOT_NAME` | Yes for the orchestrator | Snapshot used to create serving sandboxes. `build-devin-outposts-snapshot` can derive this when the variable is blank, but the orchestrator needs the actual snapshot name in `.env`. |
| `MAX_CONCURRENT_SESSIONS` | No | Default `5`. The orchestrator does not claim more sessions than this at once. |
| `ACCEPTOR_ID` | No | Leave blank for a generated ID that persists in `STATE_DIR`. Set it only when you need a stable, unique name for this orchestrator instance. Do not share one acceptor ID across instances. |
| `STATE_DIR` | No | Stores the watch cursor and generated acceptor ID. Default is `~/.devin-outposts-orchestrator`. |
| `WORKDIR` | No | Linux sandbox working directory for repo clones and the remote launch. Default is `/home/daytona/workspace`. |
| `REPOS` | No | Comma-separated clone URLs for optional pre-clone into `WORKDIR`. See repo handling below. |
| `GIT_USERNAME` | No | Optional username for private repos cloned from `REPOS`. |
| `GIT_TOKEN` | No | Optional token for private repos cloned from `REPOS`. Keep it local. |
| `DEVIN_CHROME_PATH` | No | Browser path inside Linux sandboxes. Default is `/usr/bin/chromium`. |
| `WINDOWS_WORKDIR` | No | Windows sandbox working directory. Default is `C:\repos`. |
| `DEVIN_WINDOWS_CHROME_PATH` | No | Browser path inside Windows sandboxes. Default is `C:\Program Files\Google\Chrome\Application\chrome.exe`. |

## Lifecycle and state machine

| Queue state | Orchestrator action |
|---|---|
| `phase=pending`, `session_status=pending` or `running` | Claim with this `ACCEPTOR_ID`, create or start the Daytona sandbox, clone `REPOS` when configured, then launch the pinned `devin-remote` for the entry's platform. |
| `phase=claimed`, `acceptor_id` matches this orchestrator | Re-attach on startup. If the sandbox or worker is gone, release the claim and stop or delete according to the latest queue status. |
| `session_status=suspended` | Release the claim and stop the sandbox. Daytona keeps the filesystem so the same session can resume later. |
| `session_status=terminated` | Release any held claim and delete the sandbox. |
| Queue entry missing or delete event | Treat as suspended: suspended sessions leave the queue entirely, so release any held claim and stop the sandbox while keeping its disk. |
| Claim conflict `409` | Another acceptor won the compare-and-set claim. The orchestrator leaves the session alone. |

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) covers the runtime flow behind this table: the watch loop, the serve sequence, reattach after restart, and the janitor.

## Sandbox names and labels

Serving sandboxes use this shape:

- Name: `devin-{session_id}` after stripping unsafe characters from the queue session id.
- Label: `devin.session_id={session_id}`
- Label: `devin.outpost_id={outpost_id}`
- Auto-stop and auto-delete intervals: disabled at creation. The orchestrator decides when to stop or delete.

The name lets operators find the sandbox for a Devin session in the Daytona dashboard. The labels let the janitor filter only sandboxes created by this reference implementation for the configured outpost.

## Repo handling

Use `REPOS` when the worker needs repository state before the remote launches.

```bash
REPOS=https://github.com/example/private-app.git,https://github.com/example/shared-lib.git
GIT_USERNAME=replace-with-git-username
GIT_TOKEN=replace-with-git-token
```

When `REPOS` is configured, the orchestrator creates `WORKDIR` and clones those URLs with `sandbox.git.clone()` before starting the worker. Treat `GIT_TOKEN` like any other secret. Keep it in local environment only.

## Validation checklist

Run this before relying on the orchestrator in your own environment:

1. Build the snapshot from `devin_outposts/Dockerfile.default`.
2. Create a fresh sandbox from that snapshot and verify `gh --version` works inside it.
3. Create a Devin session on the outpost.
4. Confirm the orchestrator claims it, creates a sandbox, starts the worker, and completes a smoke prompt that writes `/tmp/outposts-refimpl-smoke.txt`.
5. Let the session sleep, then message it again. Confirm the same sandbox starts and the smoke file still exists.
6. Terminate the session. Confirm the orchestrator deletes the sandbox.
7. Stop the orchestrator during an active session, start it again, and confirm it re-attaches to entries claimed by its `ACCEPTOR_ID`.

## Caveats

- Outposts APIs are in early access. Keep the queue client thin and expect endpoint shapes to change.
- The current Devin session-create API may not expose outpost selection. If so, create sessions from the Devin UI or Slack and select the outpost there.
- Windows sandboxes run the remote in a non-interactive service session. Devin's browser tool works with the snapshot's Chrome, but the Devin Desktop stream does not render, and screen capture tools such as ffmpeg `gdigrab` fail in that session.
- The default Windows snapshot ships Git, Chrome, and the Devin CLI only. Add language toolchains to `devin_outposts/provision_windows.ps1` when sessions must build or test code on Windows.

## Secret handling

- Keep real values in `.env`, shell environment, or your local secret manager only.
- Keep `.env.example` placeholders fake.
- Do not paste tokens into session prompts, logs, docs, generated artifacts, or issue comments.
- Pass secrets into subprocesses through environment variables.
