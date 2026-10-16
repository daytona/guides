# OpenAI Computer-Use Helpers with Daytona

## Overview

This example lets an OpenAI model operate a browser on a disposable Daytona desktop, using the `ComputerToolset` helper from the OpenAI Python SDK (3.31.0 or higher). Daytona provides the desktop and the mouse, keyboard, and screenshot APIs; OpenAI's helper runs the computer-use loop; your application decides which actions are allowed.

`main.py` is self-contained. It creates the sandbox, starts the computer-use desktop, opens a browser on the target page, runs the model's computer-use loop against a restrictive driver that permits screenshots and a single click, and deletes the sandbox when the run finishes.

## Features

- **Self-contained:** The script creates and deletes its own sandbox. No desktop has to exist beforehand, and nothing is left running afterwards.
- **Restrictive driver:** Only `screenshot` and one plain left click are implemented. Every other action raises.
- **Explicit consent:** The script prompts for approval before any screenshot is taken, and before the sandbox is created.
- **Safety checks are never auto-approved:** Pending safety checks are rejected, which stops the run.

## Prerequisites

- **Python:** Version 3.11 or higher is required.
- **OpenAI Python SDK:** `openai>=3.31.0`. Version 3.31.0 is the first release that ships the computer helper module (`openai.lib.computer`); earlier versions do not have it.
- **Daytona account and API key:** Get the key from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).
- **A model that supports the native `computer` tool**, for example `gpt-6-astra`.

## Environment Variables

- `OPENAI_API_KEY` — authenticates the model calls that drive the computer-use loop. Stays on your machine; it is never passed into the sandbox. Create it on the [OpenAI Developer Platform](https://platform.openai.com/api-keys).
- `OPENAI_MODEL` — the model that runs the loop. It must support the native `computer` tool. The example uses `gpt-6-astra`.
- `DAYTONA_API_KEY` — access to Daytona sandboxes. Get it from the [Daytona Dashboard](https://app.daytona.io/dashboard/keys).

Copy `.env.example` to `.env` and fill in the values.

## Getting Started

### Install dependencies

```bash
pip install "openai==3.31.0" "daytona==0.224.1" python-dotenv
```

### Run the example

```bash
python main.py
```

The program prompts for consent before it takes any screenshot. Answer `y` to continue; anything else exits without creating a sandbox.

## How It Works

1. **Create the sandbox.** The script creates a sandbox from the default Daytona snapshot, which already contains the Computer Use packages.
2. **Start the desktop.** `sandbox.computer_use.start()` brings up the virtual display and the desktop session, and the script waits until the status reports it is running.
3. **Open the browser.** A browser is launched in the background on the desktop, pointed at the target page.
4. **Connect the driver.** A driver that wraps the sandbox's screenshot and mouse APIs is handed to OpenAI's `ComputerToolset`.
5. **Run the loop.** The model requests screenshots and clicks. The driver allows exactly one plain left click inside the display bounds, raises on every other action, and always rejects pending safety checks.
6. **Check the click.** The script raises if the model never clicked. It does not check where the click landed, so the printed heading is still the model's own answer.
7. **Clean up.** The sandbox is deleted in a `finally` block, so it is removed even if the run fails.

## Safety

Screenshots of the desktop are sent to OpenAI as part of the model request, so treat everything visible on the desktop as shared with the model. The driver allows only one plain left click and raises on every other action, which bounds what a model response can do. Pending safety checks are never auto-approved; rejecting them stops the run instead of continuing silently. Run this against a disposable desktop with no real credentials, accounts, or sessions signed in.

## Links

- [OpenAI Python SDK v3.31.0 release](https://github.com/openai/openai-python/releases/tag/v3.31.0)
- [OpenAI Node SDK v7.33.0 release](https://github.com/openai/openai-node/releases/tag/v7.33.0)
- [Browser providers (Python)](https://github.com/openai/openai-python/blob/v3.31.0/docs/browser-providers.md)
- [Browser providers (Node)](https://github.com/openai/openai-node/blob/v7.33.0/docs/browser-providers.md)
- [Daytona Computer Use](https://www.daytona.io/docs/en/computer-use)
