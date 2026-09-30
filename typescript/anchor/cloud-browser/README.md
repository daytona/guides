# Anchor Cloud Browser

## Overview

This example runs your code in a [Daytona](https://www.daytona.io) sandbox and connects it to an [Anchor](https://anchorbrowser.io) cloud browser. The sandbox stays the code runtime. Chromium runs as a managed Anchor session, and the sandbox talks to it over HTTPS and CDP.

Setup follows the [Anchor Daytona integration](https://docs.anchorbrowser.io/integrations/sandboxes/daytona).

> Note: This example passes your Anchor API key into the sandbox as an environment variable. Code running in the sandbox can read it. See [Why this example uses an environment variable](#why-this-example-uses-an-environment-variable).

## Features

- **Separate roles:** Daytona runs the script. Anchor runs the browser (stealth, proxies, live view, and session lifecycle).
- **Declarative browser task:** `agentTask` opens example.com and returns the page title. The result string is `result.data.result`.
- **One session per run:** The script sets `timeout.max_duration` and `timeout.idle_timeout`, prints the live view, and deletes the session when it finishes.
- **No local browser:** The sandbox does not launch Chromium. Playwright's browser download is skipped on install.

## Prerequisites

- **Node.js:** Version 18 or higher, on the machine that starts the guide. The default Daytona sandbox image provides Node.js and npm for the script that runs inside it.
- A **Daytona account** and **API key**.
- An **Anchor API key** (bring your own key). Anchor bills browser usage on that key. Daytona does not meter it.

## Environment Variables

- `DAYTONA_API_KEY`: Required for Daytona sandboxes. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- `ANCHOR_API_KEY`: Required for the Anchor cloud browser. Get it from the [Anchor Dashboard](https://app.anchorbrowser.io).

Create a `.env` file in this directory with those variables. The host aliases `ANCHORBROWSER_API_KEY` to the same value inside the sandbox. The SDK reads `ANCHORBROWSER_API_KEY`. Without that alias, session and task calls return 401 even when `ANCHOR_API_KEY` is set.

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

The script prints a live view URL while the task runs. Open it to watch the remote Anchor session. That stream is not the Daytona sandbox desktop.

## How It Works

1. A Daytona sandbox is created with `ANCHOR_API_KEY` and `ANCHORBROWSER_API_KEY`.
2. `anchorbrowser` is installed in `/home/daytona/anchor` (the app directory, not globally). `npm install -g` is not importable from the project.
3. `browse.ts` creates one Anchor session, runs `agentTask`, and deletes the session.
4. The sandbox is deleted.

`cdp_url` contains the API key in its query string. The script never prints it. Closing Playwright only disconnects from the session, so the script calls `Sessions.deleteSession` before it exits. If the process dies first, the session timeouts still end it (`max_duration` 30 minutes, `idle_timeout` 10 minutes). See [Session Timeout](https://docs.anchorbrowser.io/advanced/session-timeout).

## Egress

If the sandbox restricts outbound traffic, allow:

- `https://api.anchorbrowser.io`
- `wss://connect.anchorbrowser.io`
- `https://live.anchorbrowser.io`

## Why this example uses an environment variable

The [Anchor Daytona page](https://docs.anchorbrowser.io/integrations/sandboxes/daytona) describes passing `ANCHOR_API_KEY` as a [Daytona Secret](https://www.daytona.io/docs/en/secrets/). Secrets substitute a placeholder into HTTPS request headers for an allowlisted host, which covers Anchor's `anchor-api-key` header on `api.anchorbrowser.io`.

This example still needs the raw key inside the sandbox. `agentTask` connects over CDP, and that URL carries the API key in the query string. Daytona substitutes secrets in HTTPS headers only, not in query strings, so a secret placeholder cannot authenticate the browser connection.

Use a secret when the sandbox only calls Anchor's HTTPS API with the key in a header, and allowlist `api.anchorbrowser.io`. Use the environment variable shown here when the sandbox connects over CDP.

## Optional: full Playwright control

`playwright` / `playwright-core` are only required when you drive the session yourself. `agentTask` is the path this guide runs. To connect with Playwright instead, install `playwright-core` in the sandbox app and replace the body of `browse.ts` with the flow from the Anchor page:

```typescript
import { chromium } from 'playwright-core'
import { client, Sessions } from 'anchorbrowser'

client.setConfig({ auth: () => process.env.ANCHORBROWSER_API_KEY })

const session = await Sessions.createSession({
  body: {
    session: {
      timeout: { max_duration: 30, idle_timeout: 10 },
    },
  },
})

console.log(`Live view: ${session.data.live_view_url}`)

const browser = await chromium.connectOverCDP(session.data.cdp_url)
const page = browser.contexts()[0].pages()[0] ?? (await browser.newPage())
await page.goto('https://example.com')
console.log('Title:', await page.title())
await browser.close()

await Sessions.deleteSession({ path: { session_id: session.data.id } })
```

You can also create the session outside the sandbox and pass `ANCHOR_CDP_URL` in. Prefer creating it inside the sandbox for this guide so the session is deleted on teardown.

## Python equivalent

The same contract works from Python inside the sandbox. Install with `pip install "anchorbrowser>=1.0"` and add `playwright` only for direct CDP control.

```python
import os
from anchorbrowser import Anchorbrowser

anchor_client = Anchorbrowser(api_key=os.getenv("ANCHORBROWSER_API_KEY"))
result = anchor_client.agent.task("Go to example.com and return the page title")
print(result.data.result)
```

## Keyless trial

Agents without a key can request a capped trial key through [Agent Access](https://docs.anchorbrowser.io/quickstart/agent-access). Trial keys are limited (1 credit, 60-minute session cap). They are for exploration, not a replacement for `ANCHOR_API_KEY`.

## License

See the main project LICENSE file for details.

## References

- [Anchor in Daytona sandboxes](https://docs.anchorbrowser.io/integrations/sandboxes/daytona)
- [Sandboxes overview](https://docs.anchorbrowser.io/integrations/sandboxes)
- [Create a Session](https://docs.anchorbrowser.io/quickstart/create-session)
- [Perform Web Task](https://docs.anchorbrowser.io/agentic-browser-control/ai-task-completion)
- [Daytona Documentation](https://www.daytona.io/docs)
