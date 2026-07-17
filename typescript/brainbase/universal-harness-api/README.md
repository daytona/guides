# Brainbase Universal Harness API on Daytona

## Overview

This example runs a background coding agent through Brainbase's [Universal Harness API](https://docs.brainbaselabs.com/api) on Daytona sandboxes. One API call describes an agent — any harness (Claude Code, Codex, OpenCode, and more), any configuration — and Brainbase runs it inside an isolated Daytona sandbox. Brainbase manages that sandbox for you: it provisions the Daytona sandbox, runs the agent's turns in it, and handles its lifecycle, so you never touch a Daytona API key or manage any infrastructure yourself.

Daytona is the default sandbox provider for the Universal Harness API. This guide also sets it explicitly (`machine_kind: "daytona"`), and every agent runs in its own isolated Daytona sandbox. The agent picks up a real ticket — a seeded project whose `pytest` suite is failing — diagnoses and fixes the bug until the suite is green, while the script streams its work live. A follow-up then asks it to add a feature on the same sandbox and re-run the tests, and the transcript is printed at the end.

## Features

- **One API call:** Describe the agent inline — harness, instructions, model, sandbox provider, even a setup `entrypoint` — and start it running.
- **Real work in an isolated Daytona sandbox:** The agent reads the code, diagnoses a failing test, fixes it, and re-runs the suite to verify — iterating until it is green.
- **Live event streaming:** Assistant text, tool calls, and turn outcomes stream back over server-sent events.
- **Multi-turn on the same sandbox:** The follow-up extends the code the agent already wrote, with full context and the same filesystem.

## Prerequisites

- **Node.js:** Version 18 or higher is required.
- **Brainbase account and API key:** Create a key at [app.brainbaselabs.com/api-keys](https://app.brainbaselabs.com/api-keys).

## Environment Variables

To run this example, you need to set the following environment variables:

- `BRAINBASE_API_KEY`: Required to authenticate API requests. Get it from [app.brainbaselabs.com/api-keys](https://app.brainbaselabs.com/api-keys).
- `BRAINBASE_BASE_URL`: Optional. Overrides the API base URL (defaults to `https://api.brainbaselabs.com`).

Create a `.env` file in the project directory with these variables.

## Getting Started

### Setup and Run

1. Install dependencies:

   ```bash
   npm install
   ```

2. Run the example:

   ```bash
   npm run start
   ```

## How It Works

When this example is run, it follows this workflow:

1. A single `POST /v2/threads` call describes the agent inline (harness `claude_code`, `machine_kind: daytona`, and an `entrypoint` that installs `pytest` and seeds a small project with a failing test suite), creates a thread, and starts the first turn from your `input`.
2. The script opens the thread's server-sent events stream with `backfill`, which replays up to the most recent `BACKFILL` (1000) events emitted since creation, so the start of the first turn is captured in the brief gap before the stream connects. The same connection then stays open across turns.
3. Brainbase boots an isolated Daytona sandbox, runs the `entrypoint` to seed the project, then runs the turn. The agent runs `pytest`, reads `intervals.py`, diagnoses the bug, fixes it, and re-runs until the suite is green — streaming its tool calls live.
4. When the turn settles (its `idle` event arrives), the script sends a follow-up on the same thread — same sandbox, full context — asking the agent to add a `total_covered` function with tests and re-run the suite. (A just-finished turn holds its run slot for a moment, so the API can briefly answer `409`; the script retries for up to 30 seconds until it frees.)
5. After the turns finish, it reads the thread to show the Daytona sandbox that ran the agent, then prints the full transcript.

## Configuration

All agent settings live in [`src/config.ts`](src/config.ts):

- **Switch harness:** Change `harness` to any of `claude_code` (default), `codex`, `cursor`, `factory`, `kafka_cloud`, `opencode`, `qoder`, or `qwen`. Everything else stays the same.
- **Sandbox provider:** This guide runs on Daytona (`machine_kind: "daytona"`), which is also the API default.
- **Pick a model:** Set `model`, or omit it to use the harness default.
- **`entrypoint`:** Bash that prepares the sandbox before the agent launches. This guide uses it to install `pytest` and seed the buggy project the agent fixes; change it to install packages, clone a repo, or seed data for your own task.
- **Optional showcases** (commented out in `src/config.ts`): `secrets` (planted into the sandbox as environment variables), `mcp_servers`, and `skills`.

## Example Output

```
Creating a "claude_code" agent on daytona...
Thread fa45300b-7247-4cad-898c-38cfd8b35f25 (agent 4578483b-ba07-424e-8e2e-b5164fe4247d)

------------------------------------------------------------
User: The Python project in /workspace has a failing test suite. Run pytest to see the failures, then find and fix the bug in intervals.py so the whole suite passes. Do not modify the tests.
  · mcp: brainbase-browser (ok), brainbase-memory (ok), brainbase-orchestration (ok)
  -> Terminal
  -> Read File

Agent: The bug: `start < last_end` should be `<=` to merge touching intervals.
  -> Edit
  -> Terminal

Agent: All 5 tests pass. Fixed the merge condition in `intervals.py` (line 8) from `start < last_end` to `start <= last_end` so touching intervals (e.g. `(1,2)` and `(2,3)`) merge correctly.
  -> mcp__brainbase-idle__brainbase_idle
● turn success: Fixed off-by-one in merge_intervals (changed `<` to `<=` on intervals.py:8) so touching intervals merge; full pytest suite now passes (5/5).

------------------------------------------------------------
User: Add a function total_covered(intervals) to intervals.py that returns the total length covered by the intervals (merge overlapping ones first), add tests for it, and run pytest again.
  -> Read File
  -> Edit
  -> Edit
  -> Edit
  -> Terminal

Agent: All 9 tests pass. Added `total_covered(intervals)` to `intervals.py` (sums lengths of merged intervals) and 4 new tests covering overlapping, touching, empty, and single-interval cases.
● turn success: All 9 tests pass. Added `total_covered(intervals)` to `intervals.py` (sums lengths of merged intervals) and 4 new tests covering overlapping, touching, empty, and single-interval cases.

------------------------------------------------------------
Ran on daytona sandbox: 5521cb88-48ee-41bc-893d-427e4b148f3f
Final status: success

Transcript (13 messages):
  user: The Python project in /workspace has a failing test suite. Run pytest to see the failures, then find and fix the bug in…
  assistant: The bug: `start < last_end` should be `<=` to merge touching intervals.
  assistant: All 5 tests pass. Fixed the merge condition in `intervals.py` (line 8) from `start < last_end` to `start <= last_end` s…
  user: Add a function total_covered(intervals) to intervals.py that returns the total length covered by the intervals (merge o…
  assistant: All 9 tests pass. Added `total_covered(intervals)` to `intervals.py` (sums lengths of merged intervals) and 4 new tests…
```

## License

See the main project LICENSE file for details.

## References

- [Brainbase Universal Harness API](https://docs.brainbaselabs.com/api)
- [Brainbase Documentation](https://docs.brainbaselabs.com)
- [Daytona Documentation](https://www.daytona.io/docs)
