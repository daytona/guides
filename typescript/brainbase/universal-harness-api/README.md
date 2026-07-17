# Brainbase Universal Harness API on Daytona

## Overview

This example runs an agent through Brainbase's [Universal Harness API](https://docs.brainbaselabs.com/api) on Daytona sandboxes. One API call describes an agent — any harness (Claude Code, Codex, OpenCode, and more), any configuration — and Brainbase runs it inside an isolated Daytona sandbox. Brainbase manages that sandbox for you: it provisions the Daytona sandbox, runs the agent's turns in it, and handles its lifecycle, so you never touch a Daytona API key or manage any infrastructure yourself.

Daytona is the default sandbox provider for the Universal Harness API. This guide also sets it explicitly (`machine_kind: "daytona"`) to make the choice clear, and every agent runs in its own isolated Daytona sandbox. The script creates a thread, streams the agent's events as it works in the sandbox, sends a follow-up on the same thread, and prints the transcript.

## Features

- **One API call:** Describe the agent inline — harness, instructions, model, and sandbox provider — and start it running.
- **Any harness on Daytona:** Switch harness with a single line; each agent runs in its own isolated Daytona sandbox.
- **Live event streaming:** Assistant text, tool calls, and turn outcomes stream back over server-sent events.
- **Multi-turn conversations:** Follow-up messages continue on the same thread, in the same sandbox, with full context.

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

1. A single `POST /v2/threads` call describes the agent inline (harness `claude_code`, `machine_kind: daytona`), creates a thread, and starts the first turn from your `input`.
2. The script opens the thread's server-sent events stream with `backfill`, which replays anything already emitted since creation so no events from the first turn are missed. The same connection then stays open across turns.
3. Brainbase boots an isolated Daytona sandbox and runs the turn. The agent's text and tool calls stream back live as it works in the sandbox.
4. When the turn settles (its `idle` event arrives), the script sends a follow-up on the same thread — same sandbox, full context. A just-finished turn holds its run slot for a moment longer, so the API can briefly answer `409` ("task is busy"); the script simply retries until the slot frees, then streams the next turn on the same connection.
5. After the turns finish, it reads the thread to show the Daytona sandbox that ran the agent, then prints the full transcript.

## Configuration

All agent settings live in [`src/config.ts`](src/config.ts):

- **Switch harness:** Change `harness` to any of `claude_code` (default), `codex`, `cursor`, `factory`, `kafka_cloud`, `opencode`, `qoder`, or `qwen`. Everything else stays the same.
- **Sandbox provider:** This guide runs on Daytona (`machine_kind: "daytona"`), which is also the API default.
- **Pick a model:** Set `model`, or omit it to use the harness default.
- **Optional showcases** (commented out in `src/config.ts`): `entrypoint` (bash that prepares the sandbox before the agent launches), `secrets` (planted into the sandbox as environment variables), `mcp_servers`, and `skills`.

## Example Output

```
Creating a "claude_code" agent on daytona...
Thread 76b1754c-c899-47cc-a196-4f33dcc1f591 (agent 32f98ac6-c5de-4b40-b2b4-f3a2c6f12e69)

------------------------------------------------------------
User: Create a file fib.py that prints the first 15 Fibonacci numbers on one line, run it with python3, and show me the output.
  · mcp: brainbase-browser (ok), brainbase-memory (ok), brainbase-orchestration (ok)
  -> Write
  -> Terminal

Agent: Created /workspace/fib.py and ran it. Output:
       0 1 1 2 3 5 8 13 21 34 55 89 144 233 377
● turn success: Created fib.py which prints the first 15 Fibonacci numbers and ran it with python3.

------------------------------------------------------------
User: Now change fib.py to print the first 30 numbers instead, and run it again.
  -> Edit
  -> Terminal

Agent: Updated to 30 numbers and ran it. Output:
       0 1 1 2 3 5 8 13 21 34 55 89 144 233 377 610 987 1597 2584 4181 6765 10946 17711 28657 46368 75025 121393 196418 317811 514229
● turn success: Changed fib.py to print first 30 Fibonacci numbers and ran it.

------------------------------------------------------------
Ran on daytona sandbox: 8e452eaa-a5ae-4f86-8464-622c5c0588a1
Final status: success

Transcript (8 messages):
  user: Create a file fib.py that prints the first 15 Fibonacci numbers on one line...
  assistant: Created /workspace/fib.py and ran it. Output: 0 1 1 2 3 5 8 13 21 34 55 89 144 233 377
  user: Now change fib.py to print the first 30 numbers instead, and run it again.
  assistant: Updated to 30 numbers and ran it. Output: 0 1 1 2 3 5 8 13 21 34 55 89 144 233 377 610 987…
```

## License

See the main project LICENSE file for details.

## References

- [Brainbase Universal Harness API](https://docs.brainbaselabs.com/api)
- [Brainbase Documentation](https://docs.brainbaselabs.com)
- [Daytona Documentation](https://www.daytona.io/docs)
