# Codex Agent

## Overview

This example runs an [OpenAI Codex](https://chatgpt.com/features/codex) agent inside a Daytona sandbox. You can interact with the agent via the CLI to run automations, build apps, and launch web apps or services using [Daytona preview links](https://www.daytona.io/docs/en/preview-and-authentication/#fetching-a-preview-link).

> Note: In this example, your OpenAI API key is passed into the sandbox environment and may be accessible to any code executed within it.

## Features

- **Secure sandbox execution:** The agent operates within a controlled environment, along with code or commands run by the agent.
- **Codex integration:** Includes the full abilities of the Codex SDK, including reading and editing code files, and running shell commands.
- **Preview deployed apps:** Use Daytona preview links to view and interact with your deployed applications.

## Prerequisites

- **Node.js:** Version 18 or higher is required

## Environment Variables

To run this example, you need to set the following environment variables:

- `DAYTONA_API_KEY`: Required for access to Daytona sandboxes. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- `SANDBOX_OPENAI_API_KEY`: Required to run Codex. Get it from [OpenAI Developer Platform](https://platform.openai.com/api-keys)

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
2. The coding agent is installed and launched inside the sandbox.
3. User queries are passed to the agent, and the result is displayed to the user.
4. When the script is terminated, the sandbox is deleted.

## Alternative: inject the key as a Daytona Secret

The quickstart passes the OpenAI key into the sandbox as a plain environment variable, so anything running inside the sandbox - including the agent itself - can read the raw key with `env`. [Daytona Secrets](https://www.daytona.io/docs/en/secrets/) keep the raw value out of the sandbox entirely: the environment variable holds only an opaque placeholder (`dtn_secret_<id>`), and Daytona's outbound proxy substitutes the real value into HTTPS request headers at egress - and only for requests to the hosts the Secret allows. An agent that dumps the environment or exfiltrates it never sees a usable key.

The Secret-based flow needs `@daytona/sdk` 0.192.0 or newer and a one-time Secret setup:

1. Create the Secret once for your organization - in the [Daytona Dashboard](https://app.daytona.io/dashboard/secrets) or with a one-off script (save as `create-secret.ts` next to this guide's `.env` and run `npx tsx create-secret.ts`):

   ```typescript
   import { Daytona } from '@daytona/sdk'
   import * as dotenv from 'dotenv'

   dotenv.config()

   async function main() {
     const value = process.env.SANDBOX_OPENAI_API_KEY
     if (!value) throw new Error('SANDBOX_OPENAI_API_KEY is not set')

     const daytona = new Daytona()
     await daytona.secret.create({
       name: 'openai-api-key',
       value,
       hosts: ['api.openai.com'], // the only host the real key may be sent to
     })
   }

   main()
   ```

2. In `src/index.ts`, swap the `OPENAI_API_KEY` env var for a `secrets:` mapping (environment variable name to Secret name):

   ```diff
    sandbox = await daytona.create({
   -  envVars: {
   -    OPENAI_API_KEY: process.env.SANDBOX_OPENAI_API_KEY || '',
   -  },
   +  secrets: {
   +    OPENAI_API_KEY: 'openai-api-key',
   +  },
    })
   ```

Inside the sandbox, `env` now shows `OPENAI_API_KEY=dtn_secret_...`, yet Codex still authenticates: it sends the key as an HTTPS `Authorization` header to `api.openai.com`, where the proxy swaps in the real value. Substitution happens only in HTTPS request headers toward allowed hosts - requests to any other host carry the harmless placeholder. See the [Secrets documentation](https://www.daytona.io/docs/en/secrets/) for the full substitution scope.

## Example Output

```
Creating sandbox...
Installing Codex agent in sandbox...
Press Ctrl+C at any time to exit.
User: make a lunar lander web app
Thinking...
🔨 ✓ Run: /bin/sh -lc ls
🔨 ✓ Run: /bin/sh -lc pwd
🔨 ✓ Run: /bin/sh -lc '/bin/ls -a'
🔨 ✓ Run: /bin/sh -lc '/bin/ls -a .daytona'
📝 Add /home/daytona/index.html
📝 Add /home/daytona/style.css
📝 Add /home/daytona/main.js
📝 Update /home/daytona/main.js
📝 Update /home/daytona/main.js
Built a playable lunar lander experience with stylized cockpit UI and physics-driven canvas gameplay.
- index.html: Hero copy, control pill, stat bar, canvas playfield with mission brief sidebar and reset control wired for keyboard/onscreen use.
- style.css: Bold dark-space treatment with gradients, neon accent palette, pill stats, responsive two-column → single-column layout, and hover states.
- main.js: Physics loop with gravity/thrust/side-thrust, fuel burn, tilt stabilization, landing pad detection, win/lose overlays, HUD updates, and keyboard handling (arrows/WASD/space, R to reset).
Usage Summary: Cached: 49152, Input: 105923, Output: 11037
User: run the server
Thinking...
🔨 ✓ Run: /bin/sh -lc 'cd /home/daytona && nohup python -m http.server 8000 >/home/daytona/server.log 2>&1 & echo $!'
Server running on port 8000 (PID 343). Open https://8000-583a999c-64f7-4ef7-9f04-b533afe4a61e.proxy.daytona.works to play. Check logs at /home/daytona/server.log if needed; stop with kill 343.
Usage Summary: Cached: 8192, Input: 24947, Output: 266
User:
Cleaning up...
```

## License

See the main project LICENSE file for details.

## References

- [Codex SDK](https://developers.openai.com/codex/sdk/)
- [Codex SDK README](https://github.com/openai/codex/blob/main/sdk/typescript/README.md)
- [Daytona Documentation](https://www.daytona.io/docs)
