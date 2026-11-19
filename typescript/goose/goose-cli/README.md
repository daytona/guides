# Goose CLI Coding Agent with Daytona

A headless coding agent powered by the open source [Goose](https://goose-docs.ai/) CLI running inside secure [Daytona sandboxes](https://www.daytona.io/), streaming its task output back to your terminal in real time.

## Features

- **Secure sandbox execution:** The Goose CLI and any code it runs stay inside an isolated Daytona sandbox.
- **Fully headless:** Runs non-interactively with a fixed provider/model and auto-approved tool calls - no setup wizard, no permission prompts.
- **Streaming output:** Parses the CLI's `stream-json` events for real-time message and tool activity.
- **Session continuity:** Once a turn completes, later prompts resume Goose's most recent session (`--resume`) for multi-turn context.
- **Preview URLs for servers:** A Daytona-aware system prompt tells Goose to write server-start commands to a script instead of running them, so they can be started outside the turn and exposed via a Daytona preview URL.

## Prerequisites

- Node.js 22.15 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- An OpenAI API key from [OpenAI Platform](https://platform.openai.com/api-keys)

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and add your API keys:

   ```bash
   DAYTONA_API_KEY=your_daytona_key
   SANDBOX_OPENAI_API_KEY=your_openai_key
   ```

## Run

```bash
npm run start
```

Then type a prompt at the `User:` prompt and watch the agent stream its work. Press Ctrl+C to exit.

## What's happening

The script creates a Daytona sandbox with `OPENAI_API_KEY`, `GOOSE_PROVIDER=openai`, and `GOOSE_MODEL=gpt-4o` injected at create time, so Goose has a provider configured without ever running its interactive `goose configure` wizard. `GOOSE_MODE=auto` auto-approves tool calls so a turn never blocks on a confirmation prompt, and `GOOSE_DISABLE_KEYRING=1` makes Goose use file-based secret storage instead of a desktop keyring that doesn't exist in the sandbox.

It installs Goose with the official install script, passing `CONFIGURE=false` so the installer skips its trailing interactive `goose configure` step (which would otherwise try to read from a controlling terminal that doesn't exist in the sandbox's exec environment and fail), and checks `goose --version` so a failed download stops the setup instead of hanging the first prompt. It then opens a single PTY for the whole conversation and runs `goose run --output-format stream-json --text "<prompt>"` for each turn, adding `--resume` once a turn has completed so Goose continues its most recent session. Each turn prints `Thinking...` while Goose starts up and reaches the model. `--output-format stream-json` emits newline-delimited JSON events that are parsed and printed live: assistant text streams as it arrives, tool calls (`toolRequest` blocks in assistant messages) print as `[tool] <name>: <command or path>` the moment Goose makes them, and failed tool results (`toolResponse` blocks, which come back in user messages) print as `[tool error] ...`. Goose reports a turn's outcome with a `complete` event, or with an `error` event when the provider rejects the request (bad key, quota, etc.), which prints as `Failed: ...`. Each command is followed by a `printf` that reports Goose's exit code as one more JSON line, so a turn also ends when Goose exits without either event, for example on a setup error it prints as plain text. The sandbox is deleted automatically on exit.

Before the first turn, a Daytona-aware system prompt is sent via Goose's native `--system` flag (only once - Goose carries it forward as part of the session `--resume` continues). It tells Goose the preview URL pattern for the sandbox and, critically, not to run servers directly: `goose run` is a one-shot command that blocks until it exits, so a foreground dev server started inside a turn would never let that turn (or the whole prompt loop) complete. Instead, Goose is told to write the server-start command to `/home/daytona/start.sh`. After every turn, the script moves that file out of the way (so each server starts once, not again after every later turn) and, if there was one, runs it in a separate Daytona session with `runAsync: true` - outside Goose entirely - so the server keeps running in the background while the conversation continues. Those server sessions are cleaned up alongside the sandbox on exit.

## Alternative: inject the key as a Daytona Secret

The quickstart passes the OpenAI key into the sandbox as a plain environment variable, so anything running inside the sandbox - including the agent itself - can read the raw key with `env`. [Daytona Secrets](https://www.daytona.io/docs/en/secrets/) keep the raw value out of the sandbox entirely: the environment variable holds only an opaque placeholder (`dtn_secret_<id>`), and Daytona's outbound proxy substitutes the real value into HTTPS request headers at egress - and only for requests to the hosts the Secret allows. An agent that dumps the environment or exfiltrates it never sees a usable key.

The Secret-based flow uses `daytona.v0` from the `@daytona/sdk` version this guide pins and needs a one-time Secret setup:

1. Create the Secret once for your organization - in the [Daytona Dashboard](https://app.daytona.io/dashboard/secrets) or with a one-off script (save as `create-secret.ts` next to this guide's `.env` and run `npx tsx create-secret.ts`):

   ```typescript
   import { Daytona } from '@daytona/sdk'
   import * as dotenv from 'dotenv'

   dotenv.config()

   async function main() {
     const value = process.env.SANDBOX_OPENAI_API_KEY
     if (!value) throw new Error('SANDBOX_OPENAI_API_KEY is not set')

     const daytona = new Daytona()
     await daytona.v0.secret.create({
       name: 'openai-api-key',
       value,
       hosts: ['api.openai.com'], // the only host the real key may be sent to
     })
   }

   main()
   ```

2. In `src/index.ts`, swap the `OPENAI_API_KEY` env var for a `secrets:` mapping (environment variable name to Secret name). The other `GOOSE_*` variables carry no credentials and stay plain env vars:

   ```diff
    sandbox = await daytona.v0.create({
      envVars: {
   -    OPENAI_API_KEY: process.env.SANDBOX_OPENAI_API_KEY,
        GOOSE_PROVIDER: 'openai',
        GOOSE_MODEL: 'gpt-4o',
        GOOSE_MODE: 'auto',
        GOOSE_DISABLE_KEYRING: '1',
      },
   +  secrets: {
   +    OPENAI_API_KEY: 'openai-api-key',
   +  },
    })
   ```

Inside the sandbox, `env` now shows `OPENAI_API_KEY=dtn_secret_...`, yet Goose still authenticates: it sends the key as the `Authorization` HTTPS request header to `api.openai.com`, where the proxy swaps in the real value. Substitution happens only in HTTPS request headers toward allowed hosts - requests to any other host carry the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets/) for the full substitution scope.

## Example Output

````
$ npm run start
Creating sandbox...
Installing Goose CLI...
Starting Goose CLI...

Agent ready. Press Ctrl+C at any time to exit.

User: Write a Python script fib.py that prints the first 10 Fibonacci numbers on one line, run it, and show me the output
Thinking...
[tool] write: /home/daytona/fib.py
[tool] shell: python3 /home/daytona/fib.py
Here is the output of the first 10 Fibonacci numbers on one line:

```
0 1 1 2 3 5 8 13 21 34
```
User: What was the last number fib.py printed? Answer in one short sentence.
Thinking...
The last number printed by `fib.py` was 34.
User: Create an index.html that says Hello from Goose on Daytona and serve the current directory with Python's http.server on port 8000
Thinking...
[tool] write: /home/daytona/index.html
[tool] write: /home/daytona/start.sh
The `index.html` file has been created, and the server is set to run on port 8000. You can view it [here](https://8000-<sandbox-id>.daytonaproxy01.net).
Running `python3 -m http.server 8000` via session command...
User:
````

In the last turn, Goose writes the server's start command to `/home/daytona/start.sh` instead of running it; the script then starts that command in its own Daytona session, and the preview URL serves the page.

## References

- [Goose Documentation](https://goose-docs.ai/docs/)
- [Goose CLI Reference](https://goose-docs.ai/docs/guides/goose-cli-commands)
- [Daytona Documentation](https://www.daytona.io/docs/)
