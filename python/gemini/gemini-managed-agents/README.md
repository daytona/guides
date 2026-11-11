# Gemini Managed Agents on Daytona

Reference implementation for running [Gemini Managed Agents](https://aistudio.google.com/docs/antigravity-agent) with a self-hosted environment backed by Daytona sandboxes. Gemini runs the agent; every shell command and file edit the agent makes runs in a Daytona sandbox you own. See the [full guide](https://www.daytona.io/docs/en/guides/gemini/gemini-managed-agents) for the architecture story; this README covers how to run the reference.

## How it works

A self-hosted environment hands the agent's tool calls to a worker you run: the environment runtime in the [`gemini-api` CLI](https://github.com/google-gemini/gemini-api-cli), which executes `execute_bash` and the file tools (`view_file`, `write_to_file`, `list_dir`, ...) in `/workspace` and streams the results back. This reference runs that worker in Daytona sandboxes, in one of two modes:

- **One worker sandbox** (`worker.py`): a long-lived sandbox runs `gemini-api environments connect`, leases the environment's interactions, and runs all of them. The sandbox holds the environment key.
- **A sandbox per interaction** (`gemini-api environments poll` and `provision_sandbox.py`): the poller runs on your host with the environment key. For each interaction, `provision_sandbox.py` creates a fresh sandbox that runs `gemini-api environments serve` with only that interaction's short-lived lease token, and deletes the sandbox when the interaction ends.

Your application creates interactions with your Gemini API key (`run_agent.py`). That key never enters a sandbox.

## Prerequisites

- A Gemini API key from a project with access to Gemini Managed Agents self-hosted environments.
- A Daytona account and API key.
- Python 3.12.
- For the per-interaction mode, the `gemini-api` CLI on the host that runs the poller:

  ```
  curl -fsSL https://raw.githubusercontent.com/google-gemini/gemini-api-cli/main/scripts/install.sh | bash
  ```

## Setup

```
python3.12 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env
# Then set GEMINI_API_KEY and DAYTONA_API_KEY.
```

## Create a self-hosted environment

```
.venv/bin/python create_environment.py
```

Creates an environment with `{"mode": "self_hosted"}` and prints the two lines to add to `.env`:

```
GEMINI_ENVIRONMENT_ID=<environment-id>
GEMINI_ENVIRONMENT_KEY=<environment-key>
```

The API returns the environment key only once. Use the environment id exactly as printed: a bare id, not `environments/<id>`.

`--snapshot NAME` stores `{"daytona": {"snapshot": NAME}}` as the environment's `custom_config`. The Gemini API passes `custom_config` through to `provision_sandbox.py` unchanged, which then creates this environment's sandboxes from `NAME` instead of the default snapshot.

## Build the worker snapshot

```
.venv/bin/python build_snapshot.py
```

Builds a Daytona snapshot from `Dockerfile` (Python 3.12, git, ripgrep, jq, and the `gemini-api` CLI pinned to v0.4.6 and checksum-verified) and names it `gemini-managed-agents-{sha8}` after the Dockerfile's SHA-256. It skips the build if that snapshot already exists. Sandboxes get 2 vCPU, 4 GB memory, and 10 GB disk; edit `build_snapshot.py` to change that.

To give the agent more tools, add them to `Dockerfile` and rerun the script.

## Run a worker

### One worker sandbox

```
.venv/bin/python worker.py
```

Creates a sandbox from the snapshot with `GEMINI_ENVIRONMENT_KEY` set, starts `gemini-api environments connect --root-dir /workspace --workdir /workspace` in it, and prints the worker's log:

```
sandbox <sandbox-id> is up; connecting a worker to environment <environment-id>
2026/11/11 13:19:23 Worker worker-<sandbox-id>-112 polling (maxConcurrent=4)
2026/11/11 13:20:02 [v1_...] Claimed interaction lease (env=<environment-id>)
2026/11/11 13:20:06 [v1_...] Executing function execute_bash
2026/11/11 13:20:10 [v1_...] Executing function write_to_file
2026/11/11 13:20:13 [v1_...] Completed interaction session
```

Ctrl-C stops the worker and deletes the sandbox. The sandbox is ephemeral with a 15-minute auto-stop, and reading the worker log is what keeps it active, so it is also deleted if the script dies.

Files stay in the sandbox across interactions while the worker runs, which suits a single user or a development loop.

### A sandbox per interaction

Run the poller from this directory:

```
export $(grep '^GEMINI_ENVIRONMENT_KEY=' .env)
gemini-api environments poll --provision-cmd ".venv/bin/python provision_sandbox.py"
```

For each interaction it leases, the poller runs `provision_sandbox.py` with a JSON payload on stdin (`interaction_id`, `lease_token`, `environment_config`, ...). The script creates an ephemeral sandbox, starts `gemini-api environments serve --interaction-id ... --lease-token ...` in it, and exits once the worker has attached. A detached copy of the script then waits for the worker to finish and deletes the sandbox.

```
2026/11/11 12:55:57 PollerController started (maxInteractions=10)
2026/11/11 12:57:17 [v1_...] Claimed interaction lease (env=<environment-id>)
2026/11/11 12:57:22 [v1_...] Dispatched interaction lease for environment <environment-id>
```

The poller discards the provisioner's stdout and only shows its stderr when provisioning fails, so each interaction gets a log file under `logs/`, including the worker's log from inside the sandbox:

```
2026-11-11T12:57:19Z created sandbox <sandbox-id> from default snapshot gemini-managed-agents-<sha8>
2026-11-11T12:57:22Z worker attached in sandbox <sandbox-id>; handed off
2026-11-11T12:57:53Z worker exited with code 0; worker log:
2026/11/11 12:57:19 [v1_...] Attached interaction session
2026/11/11 12:57:26 [v1_...] Executing function execute_bash
2026/11/11 12:57:31 [v1_...] Executing function write_to_file
2026/11/11 12:57:31 [v1_...] Executing function execute_bash
2026/11/11 12:57:41 [v1_...] Completed interaction session

2026-11-11T12:57:53Z deleted sandbox <sandbox-id>
```

Each sandbox is ephemeral, auto-stops after 15 idle minutes if the watcher is gone, and has a 2-hour TTL as a hard cap. The poller kills the provisioner after `--provision-timeout` (2 minutes by default), so `provision_sandbox.py` gives sandbox creation up to 60 seconds and the attach wait up to 45 seconds. If the worker fails to attach, for example because the lease token is no longer valid, `provision_sandbox.py` deletes the sandbox and exits non-zero, which the poller reports as a failed dispatch.

## Run an interaction

With a worker running in either mode:

```
.venv/bin/python run_agent.py "Create hello.txt and run uname -a in bash."
```

`run_agent.py` creates a streaming interaction with `google-genai`, with `environment` set to `GEMINI_ENVIRONMENT_ID`. It prints the agent's tool calls and their results to stderr and the agent's reply to stdout:

````
interaction v1_...
→ execute_bash {"Cwd":"","command":"pwd && uname -a && find .agents/skills ~/.agents/skills /.agents/skills /usr/share/agent/skills -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null; ls -la AGENTS.md .agents/AGENTS.md /AGENTS.md /.agents/AGENTS.md 2>/dev/null"}
← execute_bash (ok)
→ write_to_file {"CodeContent":"Hello, world!\n","Description":"Create hello.txt file","Overwrite":true,"TargetFile":"/workspace/hello.txt"}
← write_to_file (ok)
Created `hello.txt` and executed `uname -a`.

### Output of `uname -a`:
```
Linux <sandbox-id> 6.17.0-35-generic #35~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC Tue May 26 19:30:42 UTC 2 x86_64 GNU/Linux
```
interaction completed
````

The hostname in the `uname -a` output is the Daytona sandbox id, because the command ran in your sandbox.

`run_agent.py` uses `antigravity-preview-09-2026`; set `GEMINI_AGENT` to run another agent. The `gemini-api` CLI works as a client too:

```
export $(grep -E '^GEMINI_(API_KEY|ENVIRONMENT_ID)=' .env)
gemini-api agent run "Create hello.txt and run uname -a in bash." \
  --agent antigravity-preview-09-2026 \
  --body "{\"environment\": \"$GEMINI_ENVIRONMENT_ID\"}"
```

## Files

- `Dockerfile`: worker image, Python 3.12 slim plus the pinned `gemini-api` CLI.
- `build_snapshot.py`: builds the worker snapshot from `Dockerfile`.
- `create_environment.py`: creates a self-hosted environment and prints its id and key.
- `worker.py`: one long-lived worker sandbox running `gemini-api environments connect`.
- `provision_sandbox.py`: the `--provision-cmd` for `gemini-api environments poll`; one sandbox per interaction running `gemini-api environments serve`.
- `run_agent.py`: the application side; creates an interaction and streams it.
- `sandbox_lib.py`: snapshot naming and the helpers that start and read the in-sandbox worker.

## Configuration

`.env.example` is the source of truth for environment variables.

- `GEMINI_API_KEY`: used by `create_environment.py` and `run_agent.py`. Never sent to a sandbox.
- `GEMINI_ENVIRONMENT_ID`, `GEMINI_ENVIRONMENT_KEY`: printed by `create_environment.py`. `worker.py` passes the key into its sandbox; `gemini-api environments poll` reads it from its own environment.
- `DAYTONA_API_KEY`: used by `build_snapshot.py`, `worker.py`, and `provision_sandbox.py`.
- `GEMINI_AGENT` (optional): the agent `run_agent.py` runs. Defaults to `antigravity-preview-09-2026`.
- `SNAPSHOT_NAME` (optional): use this snapshot instead of the Dockerfile-hash name.

## Security notes

- `--root-dir /workspace` confines the file tools. `execute_bash` runs model-generated commands with no such confinement, which is why the worker runs in a sandbox rather than on your host.
- The environment key only grants access to its own environment's interactions. The CLI strips credentials from the environment of the agent's commands, but in the one-worker mode the key is still inside the sandbox, so a command could find it, for example in the worker process's environment. If that matters, use the per-interaction mode: its sandboxes only ever hold one interaction's lease token.
- In production, run the poller and your application as separate processes with separate credentials: the poller needs `GEMINI_ENVIRONMENT_KEY` and `DAYTONA_API_KEY`, the application only `GEMINI_API_KEY`. The single `.env` here is for local-machine simplicity.

## See also

- [Full Gemini Managed Agents on Daytona guide](https://www.daytona.io/docs/en/guides/gemini/gemini-managed-agents)
- [Gemini Managed Agents environments](https://aistudio.google.com/docs/agent-environment)
- [`gemini-api` self-hosted environment docs](https://github.com/google-gemini/gemini-api-cli/tree/main/docs/self-hosted)
- [Daytona documentation](https://www.daytona.io/docs/)
