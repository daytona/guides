# Letta Code Agent

## Overview

This example runs a Letta Code agent inside a Daytona sandbox. You can interact with the agent via the CLI to run automations, build apps, and launch web apps or services using [Daytona preview links](https://www.daytona.io/docs/en/preview-and-authentication/#fetching-a-preview-link).

> Note: In this example, your Letta API key is passed into the sandbox environment and may be accessible to any code executed within it.

## Features

- **Secure sandbox execution:** The agent operates within a controlled environment, along with code or commands run by the agent.
- **Letta Code integration:** Includes the full capabilities of Letta Code, including reading and editing code files, running shell commands, and persistent memory.
- **Stateful Agents:** Letta Code uses stateful agents under the hood (with the Letta API), which have built-in memory and can be resumed across sandbox sessions. Agents can also be viewed in Letta's [Agent Development Environment](https://app.letta.com/).
- **Preview deployed apps:** Use Daytona preview links to view and interact with your deployed applications.

## Prerequisites

- **Node.js:** Version 18 or higher is required

## Environment Variables

To run this example, you need to set the following environment variables:

- `DAYTONA_API_KEY`: Required for access to Daytona sandboxes. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- `SANDBOX_LETTA_API_KEY`: Required to run Letta Code. Get it from [Letta Platform](https://app.letta.com/api-keys)

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

When this example is run, the agent follows the following workflow:

1. A new Daytona sandbox is created.
2. Letta Code is installed in the sandbox.
3. Letta code is launched in [bidirectional headless mode](https://docs.letta.com/letta-code/headless#bidirectional-mode) with a Daytona-specific system prompt.
4. User queries are passed to the agent as JSON, and JSON responses are parsed and displayed to the user.
5. When the script is terminated, the sandbox is deleted.

## Alternative: inject the key as a Daytona Secret

The quickstart passes the Letta key into the sandbox as a plain environment variable, so anything running inside the sandbox - including the agent itself - can read the raw key with `env`. [Daytona Secrets](https://www.daytona.io/docs/en/secrets/) keep the raw value out of the sandbox entirely: the environment variable holds only an opaque placeholder (`dtn_secret_<id>`), and Daytona's outbound proxy substitutes the real value into HTTPS request headers at egress - and only for requests to the hosts the Secret allows. An agent that dumps the environment or exfiltrates it never sees a usable key.

The Secret-based flow needs `@daytona/sdk` 0.192.0 or newer and a one-time Secret setup:

1. Create the Secret once for your organization - in the [Daytona Dashboard](https://app.daytona.io/dashboard/secrets) or with a one-off script (save as `create-secret.ts` next to this guide's `.env` and run `npx tsx create-secret.ts`):

   ```typescript
   import { Daytona } from '@daytona/sdk'
   import * as dotenv from 'dotenv'

   dotenv.config()

   async function main() {
     const value = process.env.SANDBOX_LETTA_API_KEY
     if (!value) throw new Error('SANDBOX_LETTA_API_KEY is not set')

     const daytona = new Daytona()
     await daytona.secret.create({
       name: 'letta-api-key',
       value,
       hosts: ['api.letta.com'], // the only host the real key may be sent to
     })
   }

   main()
   ```

2. In `src/index.ts`, swap the `LETTA_API_KEY` env var for a `secrets:` mapping (environment variable name to Secret name):

   ```diff
    sandbox = await daytona.create({
   -  envVars: { LETTA_API_KEY: process.env.SANDBOX_LETTA_API_KEY },
   +  secrets: { LETTA_API_KEY: 'letta-api-key' },
    })
   ```

Inside the sandbox, `env` now shows `LETTA_API_KEY=dtn_secret_...`, yet Letta Code still authenticates: it sends the key as an HTTPS `Authorization` header to `api.letta.com`, where the proxy swaps in the real value. Substitution happens only in HTTPS request headers toward allowed hosts - requests to any other host carry the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets/) for the full substitution scope.

## Example Output

```
Creating sandbox...
Installing Letta Code...
Starting Letta Code...
Initializing agent...
Agent initialized. Press Ctrl+C at any time to exit.

You: make and run a lunar lander web server
Thinking...

🔧 TodoWrite
🔧 Write /home/daytona/workspace/index.html
🔧 TodoWrite
🔧 Start HTTP server on port 8000
🔧 BashOutput
🔧 TodoWrite
Perfect! 🚀 Your Lunar Lander game is now running!

Play the game here: https://8000-1a1ebb4b-e521-4881-87bf-494777570a8a.proxy.daytona.works

## How to Play:
- ↑ / W - Fire main thruster (slow descent)
- ← / A - Fire left thruster (move right)
- → / D - Fire right thruster (move left)

## Objective:
Land on the green landing pad with:
- Vertical speed < 2 m/s
- Horizontal speed < 1 m/s

Watch your fuel! You start with 1000 units and each thruster burns fuel. The lander starts with some horizontal drift to make it challenging. Good luck, astronaut! 🌙
```

## License

See the main project LICENSE file for details.

## References

- [Letta Code Documentation](https://docs.letta.com/letta-code/)
- [Letta Code CLI Reference](https://docs.letta.com/letta-code/cli-reference)
- [Daytona Documentation](https://www.daytona.io/docs)
