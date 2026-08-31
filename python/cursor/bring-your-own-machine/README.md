# Cursor BYOM workers on Daytona

> **Scope:** The operator host can use macOS or Linux. The Daytona worker runs only in a Linux sandbox.

## What runs where

This example uses Cursor's controller on a long-running operator host. It is not a serverless controller.

1. A user sends a request to the Cursor pool named `daytona`.
2. Cursor's cloud queues and orchestrates the request.
3. `agent worker controller` runs on the operator host and claims the request.
4. The controller calls the installed `spawn-cursor-byom-worker` command on that host.
5. The spawn command uses the Daytona API to create one sandbox from the configured snapshot.
6. The Cursor worker runs the session-start hook, which clones the requested GitHub repositories.
7. A monitor on the operator host deletes the sandbox after the worker exits.

The agent loop and model access stay in Cursor's cloud. Commands, file edits, builds, and repository data run in the Daytona sandbox.

## Prerequisites

Prepare these items before setup:

- A macOS or Linux host that stays online while the controller runs
- Python 3.12 or newer with the `venv` module
- `curl` on the operator host
- A Daytona account and [Daytona API key](https://www.daytona.io/docs/en/api-keys/)
- Enough Daytona quota for snapshot builds and one sandbox per active worker; see [Daytona limits](https://www.daytona.io/docs/en/limits/)
- A Cursor Enterprise team and a Cursor service-account API key
- A team-level Cursor GitHub App installation with access to the requested repositories
- Team-administrator access to Cursor's Cloud Agents settings

A personal Cursor API key cannot authenticate a pool worker. Use a [service-account API key](https://cursor.com/docs/account/enterprise/service-accounts).

## 1. Enable the Cursor settings

A Cursor team administrator must configure the team before the controller starts:

1. Open **Dashboard > Cloud Agents > Self-Hosted**.
2. Enable **Allow Self-Hosted Agents** for pool requests.
3. Enable Self-Hosted Pools for the team.
4. Enable GitHub token minting for self-hosted pool workers.
5. Confirm that the team's Cursor GitHub App installation can access each requested repository.

Cursor's web documentation describes `--clone-git-repos`, but pinned Linux build `2026.08.25-3e8eec8` does not include that option. This template instead uses `--mint-github-token` with the executable session-start hook `/usr/local/bin/clone-cursor-byom-repos`.

Cursor still mints a short-lived GitHub credential for each claimed request. Keep the team-level GitHub App installation and token-minting setting. Do not put a GitHub personal access token in `.env`.

See [Cursor Self-Hosted Pools](https://cursor.com/docs/cloud-agent/bring-your-own-machine/pools) for the current administrator settings and pool constraints.

## 2. Install the Cursor CLI on the operator host

Run these commands from the macOS or Linux operator host:

```bash
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
agent --version
agent worker controller --help
```

For this guide revision, `agent --version` must report `2026.08.25-3e8eec8`. The worker snapshot pins the same Cursor CLI archive.

The last command must show help for `agent worker controller`, including the required `--spawn` option.

## 3. Install this package

Start in a clean clone of `daytona-guides`:

```bash
cd python/cursor/bring-your-own-machine
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --editable .
command -v spawn-cursor-byom-worker
command -v build-cursor-byom-snapshot
```

Both commands must resolve inside the current `.venv`.

## 4. Set the operator environment

Create the local environment file:

```bash
cp .env.example .env
```

Edit `.env` and set these values:

```dotenv
DAYTONA_API_KEY=replace-with-your-daytona-api-key
SNAPSHOT_NAME=
CURSOR_API_KEY=replace-with-your-cursor-service-account-key

CURSOR_WORKER_IDLE_RELEASE_TIMEOUT=900
MONITOR_POLL_SECONDS=5
SANDBOX_CREATE_TIMEOUT_SECONDS=120
SANDBOX_LAUNCH_TIMEOUT_SECONDS=60
```

Leave `SNAPSHOT_NAME` empty so the builder derives a stable name from the snapshot-content hash. Never commit `.env`.

## 5. Build the worker snapshot

The snapshot contains Linux, `git`, Cursor CLI `2026.08.25-3e8eec8`, and the executable repository-clone hook. It does not contain either API key.

Run the installed builder:

```bash
build-cursor-byom-snapshot
```

Build progress goes to standard error. Success writes one JSON object to standard output:

```json
{"reused":false,"snapshot_name":"cursor-byom-default-1234abcd","state":"active"}
```

A repeated build can return `"reused":true`. Copy the exact `snapshot_name` value into `.env`:

```dotenv
SNAPSHOT_NAME=cursor-byom-default-1234abcd
```

The value above is only an example. Use the value from your own JSON output. See [Daytona snapshots](https://www.daytona.io/docs/en/snapshots/).

## 6. Start the controller

Load the operator settings and start the controller from the guide directory:

```bash
set -a; source .env; set +a
agent worker controller --spawn "$(pwd)/.venv/bin/spawn-cursor-byom-worker" --pool daytona
```

Keep this foreground process running. Cursor supplies the claim values when it invokes the spawn command.

Do not run `spawn-cursor-byom-worker` directly for normal operation. A direct run does not have the controller-supplied claim values.

## 7. Submit one pool request

Use the Cloud Agents UI or the documented API.

### UI

1. Open [Cursor Agents](https://cursor.com/agents).
2. Create an agent for a GitHub repository.
3. Select the self-hosted pool named `daytona`.
4. Submit the request while the controller runs.

### API example

The service-account key in `CURSOR_API_KEY` can authenticate this documented request. Replace the repository URL before use:

```bash
curl --request POST \
  --url https://api.cursor.com/v1/agents \
  -u "$CURSOR_API_KEY:" \
  --header 'Content-Type: application/json' \
  --data '{
    "prompt": {
      "text": "Add a health check and document how to run it"
    },
    "env": {
      "type": "pool",
      "name": "daytona"
    },
    "repos": [
      {
        "url": "https://github.com/your-org/your-repo",
        "startingRef": "main"
      }
    ]
  }'
```

The response contains the agent ID, run state, and agent URL. See [Create An Agent](https://cursor.com/docs/cloud-agent/api/endpoints#create-an-agent) for the full request and response contract.

Use an HTTPS GitHub repository URL. The worker's minted token does not authenticate an SSH remote.

## Expected outputs and proof

A successful spawn writes one compact JSON object through the controller logs:

```json
{"sandbox_id":"...","sandbox_name":"cursor-worker-...","worker_id":"worker-...","request_id":"bc-..."}
```

Use these proof steps for each deployment:

1. Confirm that the API response or UI shows a request for pool `daytona`.
2. Confirm that the controller logs contain the matching `worker_id` and `request_id`.
3. Confirm that Daytona shows the matching sandbox and `cursor.worker_id`, `cursor.request_id`, and `cursor.pool` labels.
4. Confirm that the Cursor agent reaches a running state.
5. Confirm that the requested HTTPS repository exists under `/home/daytona/workspace` in the sandbox.
6. Confirm that the agent completes and that the host monitor deletes the sandbox.

The worker stores its process ID at `/tmp/cursor-byom/worker.pid`. It writes worker output to `/tmp/cursor-byom/worker.log` inside the sandbox.

This repository does not claim an Enterprise end-to-end proof. A coordinator must complete the proof steps with an Enterprise team before marking a deployment ready.

## Settings and ownership

| Variable | Owner | Required | Purpose |
| --- | --- | --- | --- |
| `DAYTONA_API_KEY` | Operator | Yes | Creates, finds, and deletes Daytona sandboxes. The host monitor also uses it. |
| `SNAPSHOT_NAME` | Operator | Yes | Selects the active Daytona snapshot from the builder output. |
| `CURSOR_API_KEY` | Operator | Yes | Authenticates the controller and the claimed Cursor worker. Use a service-account key. |
| `CURSOR_WORKER_IDLE_RELEASE_TIMEOUT` | Operator | No | Keeps a completed worker available for follow-up work. Default: `900` seconds. |
| `MONITOR_POLL_SECONDS` | Operator | No | Sets the host monitor interval. Default: `5` seconds. |
| `SANDBOX_CREATE_TIMEOUT_SECONDS` | Operator | No | Sets the Daytona create and delete timeout. Default: `120` seconds. |
| `SANDBOX_LAUNCH_TIMEOUT_SECONDS` | Operator | No | Sets the worker launch timeout. Default: `60` seconds. |
| `CURSOR_AGENT_WORKER_ID` | Cursor controller | Yes | Gives the claimed worker its stable ID and its deterministic sandbox name. |
| `CURSOR_POOL` | Cursor controller | Yes | Selects the pool passed to the sandbox worker. |
| `CURSOR_REQUEST_ID` | Cursor controller | Yes | Identifies the claim for labels and failure release. |
| `CURSOR_REPO_URL`, `CURSOR_REPO_URLS` | Cursor controller | No | Provide claimed repository metadata. `CURSOR_REPO_URLS` is a JSON string array. |
| `CURSOR_WORKER_NAME` | Cursor controller | No | Provides an optional display name to the worker. |
| `CURSOR_API_URL`, `CURSOR_API_ENDPOINT` | Cursor controller | No | Override the Cursor API base for claim release. |
| `CURSOR_WORKER_WORKSPACE_DIR` | Cursor worker | Yes for the hook | Gives the hook the directory selected by `--worker-dir`. |

Do not add controller-owned or worker-owned values to `.env`. The controller and worker set them at run time.

## Lifecycle and cleanup

The spawn command derives one stable sandbox name from `CURSOR_AGENT_WORKER_ID`. Before each claim attempt, it deletes any existing sandbox with that name.

The spawn command then creates a fresh sandbox from `SNAPSHOT_NAME` and launches one new worker. A retry never trusts prior files or processes.

For a claim with repository metadata, the sandbox worker runs this logical command:

```bash
/usr/local/bin/agent worker --pool "$CURSOR_POOL" \
  --worker-dir /home/daytona/workspace \
  --management-addr 0.0.0.0:8080 \
  --mint-github-token \
  --on-session-start /usr/local/bin/clone-cursor-byom-repos \
  --idle-release-timeout 900 \
  start
```

The configured timeout replaces `900`. The management address stays inside the sandbox; this guide does not publish it.
The launcher uses non-login `sh -c` and the absolute `/usr/local/bin/agent` path. Login files and workspace `PATH` entries cannot select the worker executable.

At session start, Cursor sends one JSON object to the hook through standard input. The object has this form:

```json
{
  "hook_event_name": "sessionStart",
  "repo_urls": ["https://github.com/your-org/your-repo"],
  "repos": [
    {
      "repo_url": "https://github.com/your-org/your-repo",
      "ref": "main",
      "primary": true
    }
  ]
}
```

The hook uses `repos` when that array is present. It uses `repo_urls` as a fallback. The JSON does not contain the minted credential.

The worker sets `CURSOR_WORKER_WORKSPACE_DIR` from `--worker-dir`. The hook clones each repository into a stable, URL-specific directory under `/home/daytona/workspace`.

The hook removes a partial clone and retries `git clone` up to five times. The delays allow the minted GitHub credential to become available. If all attempts fail, the hook writes one actionable error to standard error and exits with status `1`.

After a successful launch, the operator host starts a detached monitor. The monitor receives only the Daytona key, sandbox ID, worker PID, and monitor settings.

When the Cursor worker exits, the host monitor deletes the Daytona sandbox. Daytona auto-stop plus delete-on-stop is the cleanup fallback if the monitor cannot complete its work.

If startup fails, the spawn command tries to release the Cursor claim. It also deletes the fresh sandbox. The command then exits with a redacted error.

## Network and secret boundaries

No inbound port is required. Permit these outbound HTTPS destinations:

| Runs from | Required destination |
| --- | --- |
| Operator host | `cursor.com` for CLI installation |
| Operator host | `downloads.cursor.com` for Cursor CLI downloads |
| Operator host | The Python package index configured for `pip` when this package is installed |
| Operator host | `api.cursor.com` for the controller, agent API, and claim release |
| Operator host | `https://app.daytona.io/api` for Daytona API access |
| Daytona sandbox | `api2.cursor.sh` or `api2direct.cursor.sh` for the Cursor worker session |
| Daytona sandbox | `cloud-agent-artifacts.s3.us-east-1.amazonaws.com` for optional artifact uploads |
| Daytona sandbox | The requested HTTPS Git host, plus package registries and tool-specific hosts needed by the task |

Prefer the exact artifact host. A wildcard for all `*.s3.us-east-1.amazonaws.com` creates a larger egress boundary.

The operator host holds both API keys. The Daytona sandbox receives the Cursor service-account key, worker ID, and optional worker name.

Cursor requires the service-account key inside the Cursor worker process. Agent tools and repository code run as the same OS user as that process.

Untrusted agent code can potentially inspect same-user process state and obtain the Cursor key. Treat this access as an unavoidable trust boundary.

The non-login shell and absolute agent path protect worker startup from login files and workspace `PATH` entries. They cannot fully hide the Cursor key from code in the same sandbox.

Use these controls for each deployment:

- Use one dedicated, least-privilege Cursor service account for each customer.
- Give the service account only the access that its worker pool requires.
- Rotate the Cursor key regularly and immediately after suspected exposure.
- Create one fresh sandbox for each claim.
- On a retry, replace the deterministic sandbox. Do not trust its files or processes.
- Do not reuse a sandbox, service account, or Cursor key across customers.

The Daytona sandbox does not receive the Daytona key. The host monitor receives the Daytona key, but it does not receive the Cursor key.

Cursor sends the short-lived GitHub token to the claimed worker. This guide stores no GitHub token.

Cursor still receives file chunks used for inference and uploaded Cloud Agent artifacts. Review [Cursor's security and network model](https://cursor.com/docs/cloud-agent/security-network) before production use.

## Troubleshooting

### `agent` is not found

Run `export PATH="$HOME/.local/bin:$PATH"` again. Then run `agent --version` and `agent worker controller --help`.

### The CLI version differs

Do not assume controller and worker compatibility. Confirm the operator CLI contract against worker version `2026.08.25-3e8eec8` before use.

### The controller rejects the Cursor key

Confirm that `CURSOR_API_KEY` is an Enterprise service-account key. Run `set -a; source .env; set +a` again after each edit.

### The spawn command reports missing `CURSOR_AGENT_WORKER_ID`, `CURSOR_POOL`, or `CURSOR_REQUEST_ID`

Start the command through `agent worker controller`. Do not set claim values by hand or run the spawn command directly.

### The request stays queued

Confirm that the controller runs with `--pool daytona`. Confirm that the request also targets pool `daytona`.

Confirm that **Allow Self-Hosted Agents** is enabled. If the API reports an unknown pool, register or select `daytona` in the Cursor Self-Hosted Pools dashboard first.

### The pinned Linux CLI rejects `--clone-git-repos`

The Cursor web documentation mentions this option, but Linux build `2026.08.25-3e8eec8` does not include it. Do not add the option to this template.

Rebuild the snapshot from this guide. The template uses `--mint-github-token` and `/usr/local/bin/clone-cursor-byom-repos` instead.

### Repository clone fails

Inspect `/tmp/cursor-byom/worker.log` for the hook's error. Confirm all these requirements:

- The repository URL uses HTTPS.
- The team's Cursor GitHub App installation can access the repository.
- A team administrator enabled GitHub token minting.
- The snapshot contains the executable `/usr/local/bin/clone-cursor-byom-repos`.
- The worker uses `--mint-github-token` and `--on-session-start /usr/local/bin/clone-cursor-byom-repos`.
- The request targets the named, any-repo pool `daytona`, not `default`.
- `/home/daytona/workspace` is writable by the `daytona` user.

The hook retries each clone up to five times before it reports a credential error. Cursor leaves a clone-failed request in the queue. Correct the setting before the next claim.

### Snapshot creation fails or times out

Confirm `DAYTONA_API_KEY`, the selected Daytona organization, and the current [Daytona limits](https://www.daytona.io/docs/en/limits/). Increase `SANDBOX_CREATE_TIMEOUT_SECONDS` only when the Daytona operation needs more time.

### The worker process fails to launch

Open the sandbox before fallback cleanup completes. Inspect `/tmp/cursor-byom/worker.log`. Confirm that the pinned Cursor CLI and `/usr/local/bin/clone-cursor-byom-repos` exist in the snapshot.

### A sandbox remains after the worker exits

Confirm that the operator host stayed online and retained Daytona API access. Check the sandbox state in Daytona, then delete the stale sandbox after you confirm no worker uses it.

### A failed startup leaves a claimed request

Use Cursor's documented [release-claim endpoint](https://cursor.com/docs/cloud-agent/api/endpoints#release-a-claim). Release only the request ID shown by the failed controller operation.
