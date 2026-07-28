# Amp Code Coding Agent with Daytona

A coding agent powered by the [Amp Code CLI](https://ampcode.com/) running inside secure [Daytona sandboxes](https://www.daytona.io/).

## Prerequisites

- Node.js 18 or newer
- A Daytona API key from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- An Amp API key from [Amp Settings](https://ampcode.com/settings)
- **Amp paid credits** - Execute mode requires paid credits. [Add credits here](https://ampcode.com/pay)

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and add your API keys:

   ```bash
   DAYTONA_API_KEY=your_daytona_key
   SANDBOX_AMP_API_KEY=your_amp_key
   ```

## Usage

Run the agent:

```bash
npm run start
```

The agent gets a Daytona-aware system prompt: sandbox context, the preview URL pattern, and instructions to write server startup commands to `/home/daytona/start.sh` instead of executing them directly in Amp.

The agent will:

1. Create a Daytona sandbox
2. Install the Amp CLI in the sandbox
3. Start an interactive prompt loop using CLI-per-turn mode with thread continuity
4. If `/home/daytona/start.sh` exists after a turn, run it via a Daytona process session command

Example session:

```
$ npm run start
Creating sandbox...
Installing Amp CLI...
Starting Amp Code...
Thinking...
Got it! I'm ready to help. What would you like to build or work on?

Agent ready. Press Ctrl+C at any time to exit.

User: say hello
Thinking...
Hello! 👋 How can I help you today?

User:
```

## Features

- Secure, isolated execution in Daytona sandboxes
- Amp CLI with streaming JSON output for real-time updates
- Thread-based session continuity across multiple turns
- Automatic cleanup on exit

## How It Works

This example uses a PTY (pseudo-terminal) to stream output from Amp CLI, running one command per user turn with thread-based session continuity:

1. A PTY is created for streaming output from Amp commands
2. First prompt: Run `amp --dangerously-allow-all --stream-json -m smart -x "prompt"` and capture the thread ID from the streaming JSON init message
3. Follow-up prompts: Run `amp --dangerously-allow-all --stream-json -m smart -x "prompt" threads continue <thread-id>`
4. If the thread ID isn't captured from the stream, fall back to parsing `amp threads list` text output
5. Each command streams JSON output for real-time display of assistant messages and tool usage

## Alternative: inject the key as a Daytona Secret

The quickstart passes the Amp key into the sandbox as a plain environment variable, so anything running inside the sandbox - including the agent itself - can read the raw key with `env`. [Daytona Secrets](https://www.daytona.io/docs/en/secrets/) keep the raw value out of the sandbox entirely: the environment variable holds only an opaque placeholder (`dtn_secret_<id>`), and Daytona's outbound proxy substitutes the real value into HTTPS request headers at egress - and only for requests to the hosts the Secret allows. An agent that dumps the environment or exfiltrates it never sees a usable key.

The Secret-based flow needs `@daytona/sdk` 0.192.0 or newer and a one-time Secret setup:

1. Create the Secret once for your organization - in the [Daytona Dashboard](https://app.daytona.io/dashboard/secrets) or with a one-off script (save as `create-secret.ts` next to this guide's `.env` and run `npx tsx create-secret.ts`):

   ```typescript
   import { Daytona } from '@daytona/sdk'
   import * as dotenv from 'dotenv'

   dotenv.config()

   async function main() {
     const value = process.env.SANDBOX_AMP_API_KEY
     if (!value) throw new Error('SANDBOX_AMP_API_KEY is not set')

     const daytona = new Daytona()
     await daytona.secret.create({
       name: 'amp-api-key',
       value,
       hosts: ['ampcode.com'], // the only host the real key may be sent to
     })
   }

   main()
   ```

2. In `src/index.ts`, swap the `AMP_API_KEY` env var for a `secrets:` mapping (environment variable name to Secret name):

   ```diff
    sandbox = await daytona.create({
   -  envVars: { AMP_API_KEY: process.env.SANDBOX_AMP_API_KEY },
   +  secrets: { AMP_API_KEY: 'amp-api-key' },
    })
   ```

Inside the sandbox, `env` now shows `AMP_API_KEY=dtn_secret_...`, yet the Amp CLI still authenticates: it sends the key as an HTTPS request header to `ampcode.com`, where the proxy swaps in the real value. Substitution happens only in HTTPS request headers toward allowed hosts - requests to any other host carry the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets/) for the full substitution scope.

## Learn More

- [Amp Manual - CLI](https://ampcode.com/manual#cli)
- [Amp Manual - Streaming JSON](https://ampcode.com/manual#cli-streaming-json)
- [Daytona Documentation](https://www.daytona.io/docs)
