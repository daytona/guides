# AI App Builder — Convex + Daytona

Describe an app in a prompt. An LLM writes the code, a [Daytona](https://www.daytona.io) sandbox runs it, and [Convex](https://www.convex.dev) streams every build step to the browser — ending with the running app rendered live in an iframe via a Daytona preview URL.

Built on the [`@daytona/convex`](https://www.npmjs.com/package/@daytona/convex) component ([directory listing](https://www.convex.dev/components/daytona/convex)).

## How it works

```
Browser (React + useQuery — live)
   │  "build me a pomodoro timer"
   ▼
Convex action (builder.build)
   ├─ creates a Daytona sandbox            ──▶ status: "creating sandbox"
   ├─ LLM generates src/App.jsx (ai SDK)   ──▶ status: "generating code"
   ├─ writes Vite scaffold + generated app ──▶ status: "writing files"
   ├─ npm install in the sandbox           ──▶ status: "installing dependencies"
   ├─ starts the dev server (backgrounded) ──▶ status: "starting dev server"
   └─ signed preview URL                   ──▶ status: "ready" → iframe renders it
```

Every `status` update is a Convex document patch, and the UI subscribes with `useQuery` — so the build timeline animates live with zero polling code, survives page refreshes mid-build, and is visible to every open client at once. During generation the LLM's output streams into the row (`draftCode`, throttled), so the code visibly writes itself in the UI — durably: refresh mid-stream and it resumes.

Follow-up prompts ("make it dark mode") regenerate the app file and write it into the sandbox — Vite's file watcher hot-reloads the iframe within a second.

## Prerequisites

- Node.js 20+
- A [Daytona API key](https://app.daytona.io/dashboard/keys)
- An [OpenAI API key](https://platform.openai.com/api-keys)

## Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/daytona/guides.git
cd guides/typescript/convex/ai-app-builder
npm install
```

Start a Convex dev deployment (creates a free local/anonymous deployment on first run — or log in at the prompt to use a cloud dev deployment; all steps are identical either way):

```bash
npx convex dev --once
```

Set the API keys on the deployment (they're used by Convex actions, never exposed to the browser):

```bash
npx convex env set DAYTONA_API_KEY dtn_...
npx convex env set OPENAI_API_KEY sk-...
```

## Run

```bash
npm run dev
```

Open http://localhost:5173, type a prompt like *"a kanban board with three columns"*, and watch the build steps stream in until the app appears. Then try an edit — *"make it dark mode"* — and watch the iframe hot-reload.

Refresh the page mid-build: the timeline keeps going. That's the Convex part.

## Project structure

```
ai-app-builder/
├── convex/
│   ├── convex.config.ts   # installs the Daytona component (app.use(daytona))
│   ├── schema.ts          # apps table — one row per generated app
│   ├── apps.ts            # reactive list query + status-patch mutations
│   ├── builder.ts         # build & iterate actions: LLM → sandbox pipeline
│   └── scaffold.ts        # fixed Vite scaffold + LLM system prompt
├── src/
│   ├── App.tsx            # prompt form, live build timeline, iframe previews
│   ├── main.tsx           # ConvexProvider setup
│   └── index.css
└── index.html
```

## Component APIs used

| Call | Purpose |
| --- | --- |
| `daytona.createSandbox` | isolated sandbox per generated app (auto-stops after 15 idle minutes, auto-deletes after 2 hours) |
| `daytona.writeFile` | write the Vite scaffold and each generated/updated `App.jsx` |
| `daytona.run` | `npm install`, start the dev server (backgrounded with `nohup … &`), readiness poll |
| `daytona.getPreviewUrl` | signed URL for port 3000, rendered in the iframe |

## Security note

This is a development example: its Convex functions are unauthenticated, and anyone with your deployment URL could trigger LLM generations and sandbox usage on your keys. Run it against a local/dev deployment. Before deploying anything like this publicly, add authentication in the Convex functions and scope sandboxes per user with the component's `userKey` (see the [component's authorization docs](https://github.com/daytona/integrations/tree/main/packages/convex#authorization)).

## Sandbox lifecycle & cost notes

Generated sandboxes are labeled `created-by: convex-ai-app-builder`, pause after 15 idle minutes, and auto-delete after 2 hours — so experiments clean themselves up. Delete one immediately from the [Daytona dashboard](https://app.daytona.io) or with `daytona.deleteSandbox`.

## License

Apache-2.0
