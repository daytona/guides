# Browser Testing a Sandbox App (Notte + Daytona)

## Overview

This guide serves a small web app from a Daytona sandbox and tests it with a [Notte](https://notte.cc) cloud browser. It is the pattern for agents that build or run code in a sandbox and then need a real browser to check the result.

The browser runs on Notte, not inside the sandbox, so the sandbox never installs or launches Chromium. `browser_test.py` creates the sandbox, serves the app on a signed preview URL, then opens it with a Notte browser twice: once with Playwright over CDP through the Notte SDK, and once with [Notte CLI](https://github.com/nottelabs/notte-cli) commands.

## Features

- **No browser in the sandbox:** Chromium runs as a managed Notte session; the sandbox only serves the app
- **Signed preview URL:** `create_signed_preview_url` embeds the token in the URL, so the remote browser needs no auth header
- **Skips the preview warning page:** Notte sessions send `X-Daytona-Skip-Preview-Warning: true` on every request
- **Playwright over CDP:** `session.page` is a Playwright page connected to the Notte browser; the script reads the to-do list and saves a screenshot
- **Notte CLI:** the same commands a coding agent would run add a to-do and scrape the page to confirm it
- **Works on every tier:** the sandbox makes no outbound calls, so the default network policy is enough

## Requirements

- **Python:** 3.11 or higher
- **Notte CLI:** `curl -fsSL https://notte.cc/install-cli.sh | sh`

## Environment Variables

- `DAYTONA_API_KEY`: Required for Daytona sandbox access. Get it from [Daytona Dashboard](https://app.daytona.io/dashboard/keys)
- `DAYTONA_API_URL`: The Daytona API endpoint, `https://app.daytona.io/api` for Daytona Cloud (already set in `.env.example`)
- `NOTTE_API_KEY`: Required for Notte browser sessions. Get it from [Notte Console](https://console.notte.cc)

## Getting Started

1. Create and activate a virtual environment:

```bash
python3.11 -m venv venv
source venv/bin/activate
```

2. Install dependencies and the Notte CLI:

```bash
pip install -e .
curl -fsSL https://notte.cc/install-cli.sh | sh
```

Playwright only connects to the remote browser, so there is no need to run `playwright install`.

3. Set your API keys:

```bash
cp .env.example .env
# edit .env with your API keys
```

4. Run the test:

```bash
python browser_test.py
```

Open the printed viewer URL to watch the browser while the script runs.

## How It Works

1. **Sandbox:** `Daytona().create()` starts a sandbox from the `daytona-small` snapshot, uploads `index.html` and runs `python3 -m http.server 3000` in a background session.
2. **Preview URL:** `sandbox.create_signed_preview_url(3000, expires_in_seconds=3600)` returns a URL that anyone can open for an hour, with the token embedded.
3. **Playwright:** a Notte session opens the URL through `session.page`, reads the two starting to-dos and takes a screenshot to `screenshots/app.png`.
4. **Notte CLI:** `notte sessions start`, `notte page goto`, `notte page fill`, `notte page click` and `notte page scrape` add a to-do and confirm the page now shows 3 to-dos.
5. **Cleanup:** both browser sessions stop and the sandbox is deleted.

## Using Your Own App

Replace `APP_HTML` and `start_app()` with whatever runs in your sandbox. Any server listening on a sandbox port is reachable through a preview URL, so the browser code does not change.

## Learn More

- [Daytona preview URLs](https://www.daytona.io/docs/en/preview)
- [Connect Playwright to a Notte session](https://docs.notte.cc/features/sessions/playwright)
- [Notte CLI](https://github.com/nottelabs/notte-cli)
