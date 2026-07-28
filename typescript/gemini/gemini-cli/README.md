# Gemini CLI Coding Agent with Daytona

A headless coding agent powered by the [Gemini CLI](https://geminicli.com/) running inside secure [Daytona sandboxes](https://www.daytona.io/), streaming its task output back to your terminal in real time.

## Features

- **Secure sandbox execution:** The Gemini CLI and any code it runs stay inside an isolated Daytona sandbox.
- **Fully headless:** Runs non-interactively with no browser OAuth and no permission prompts.
- **Streaming output:** Parses the CLI's `stream-json` events for real-time tool and message activity.
- **Session continuity:** Reuses the Gemini session across prompts (`-r`) for multi-turn context.

## Prerequisites

- Node.js 20 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and add your API keys:

   ```bash
   DAYTONA_API_KEY=your_daytona_key
   SANDBOX_GEMINI_API_KEY=your_gemini_key
   ```

## Run

```bash
npm run start
```

Then type a prompt at the `User:` prompt and watch the agent stream its work. Press Ctrl+C to exit.

## What's happening

The script creates a Daytona sandbox with `GEMINI_API_KEY` and `GEMINI_CLI_TRUST_WORKSPACE=true` injected at create time, so the Gemini CLI authenticates headlessly (skipping browser OAuth) and bypasses the workspace-trust prompt that would otherwise block runs in a fresh directory. It installs `@google/gemini-cli` in the sandbox, then opens a PTY and runs `gemini -p "<prompt>" --yolo --output-format stream-json` for each turn. `--yolo` auto-approves tool calls so the run never blocks on a permission prompt, and `--output-format stream-json` emits newline-delimited JSON events that are parsed and printed live. The session ID from the `init` event is reused with `-r` for multi-turn continuity, and the sandbox is deleted automatically on exit.

## Alternative: inject the key as a Daytona Secret

The quickstart passes the Gemini key into the sandbox as a plain environment variable, so anything running inside the sandbox - including the agent itself - can read the raw key with `env`. [Daytona Secrets](https://www.daytona.io/docs/en/secrets/) keep the raw value out of the sandbox entirely: the environment variable holds only an opaque placeholder (`dtn_secret_<id>`), and Daytona's outbound proxy substitutes the real value into HTTPS request headers at egress - and only for requests to the hosts the Secret allows. An agent that dumps the environment or exfiltrates it never sees a usable key.

The Secret-based flow needs `@daytona/sdk` 0.192.0 or newer and a one-time Secret setup:

1. Create the Secret once for your organization - in the [Daytona Dashboard](https://app.daytona.io/dashboard/secrets) or with a one-off script (save as `create-secret.ts` next to this guide's `.env` and run `npx tsx create-secret.ts`):

   ```typescript
   import { Daytona } from '@daytona/sdk'
   import * as dotenv from 'dotenv'

   dotenv.config()

   async function main() {
     const value = process.env.SANDBOX_GEMINI_API_KEY
     if (!value) throw new Error('SANDBOX_GEMINI_API_KEY is not set')

     const daytona = new Daytona()
     await daytona.secret.create({
       name: 'gemini-api-key',
       value,
       hosts: ['generativelanguage.googleapis.com'], // the only host the real key may be sent to
     })
   }

   main()
   ```

2. In `src/index.ts`, swap the `GEMINI_API_KEY` env var for a `secrets:` mapping (environment variable name to Secret name). `GEMINI_CLI_TRUST_WORKSPACE` carries no credentials and stays a plain env var:

   ```diff
    sandbox = await daytona.create({
      envVars: {
   -    GEMINI_API_KEY: process.env.SANDBOX_GEMINI_API_KEY,
        GEMINI_CLI_TRUST_WORKSPACE: 'true',
      },
   +  secrets: {
   +    GEMINI_API_KEY: 'gemini-api-key',
   +  },
    })
   ```

Inside the sandbox, `env` now shows `GEMINI_API_KEY=dtn_secret_...`, yet the CLI still authenticates: it sends the key as the `x-goog-api-key` HTTPS request header to `generativelanguage.googleapis.com`, where the proxy swaps in the real value. Substitution happens only in HTTPS request headers toward allowed hosts - requests to any other host carry the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets/) for the full substitution scope.

## Example Output

```
$ npm run start
Creating sandbox...
Installing Gemini CLI...
Starting Gemini CLI...

Agent ready. Press Ctrl+C at any time to exit.

User: Write a Python script mandelbrot.py that renders the Mandelbrot set as ASCII art roughly 40 columns by 20 rows, then run it and show the rendered output
[tool] write_file
[tool] run_shell_command
[tool] replace
[tool] run_shell_command
I have successfully created and executed the Python script mandelbrot.py to render the Mandelbrot set as ASCII art.

               ......-:@...
                .......:%+:....
              ........:*@@*:....
             .....+-:--=@@-:::::.
           .......:@%@@@@@@@@=#+..
        .........==@@@@@@@@@@@+:..
     .....-::::::%@@@@@@@@@@@@@%:..
  .......:-@*@%--@@@@@@@@@@@@@@%:..
 .......::%@@@@@+@@@@@@@@@@@@@@#...
 ..-:.::+@@@@@@@@@@@@@@@@@@@@@@:...
 ..-:.::+@@@@@@@@@@@@@@@@@@@@@@:...
 .......::%@@@@@+@@@@@@@@@@@@@@#...
  .......:-@*@%--@@@@@@@@@@@@@@%:..
     .....-::::::%@@@@@@@@@@@@@%:..
        .........==@@@@@@@@@@@+:..
           .......:@%@@@@@@@@=#+..
             .....+-:--=@@-:::::.
              ........:*@@*:....
                .......:%+:....
                  ......-:@...

User:
```

> **Why the extra steps?** The agent wrote `mandelbrot.py` and ran it, then made a small `replace` edit and ran it again to refine the rendering. A single `write_file` plus `run_shell_command` already satisfies the prompt; the extra edit-and-rerun is the agent choosing to improve its own output.

## References

- [Gemini CLI Documentation](https://geminicli.com/docs/)
- [Daytona Documentation](https://www.daytona.io/docs/)
