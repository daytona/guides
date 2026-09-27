# macOS AppleScript Recorder (Anthropic + use.computer)

## Overview

This example demonstrates how to control a real macOS sandbox with an LLM and record the whole run as a video you can watch afterward. It uses use.computer to provision a macOS sandbox, and the Anthropic API to generate AppleScript code which is run in the sandbox.

In this example, the script asks Claude to write an AppleScript that opens TextEdit and types a haiku, runs it in a fresh macOS sandbox, and saves a video of the session to your machine.

## Features

- **Real macOS sandbox:** Created on your use.computer reservation, torn down when the script finishes
- **Natural language interface:** Describe the task in plain English; Claude writes the AppleScript
- **Screen recording:** The entire session is recorded and downloaded as an MP4 so you can see exactly what happened
- **No agent loop:** One script, one LLM call, one script execution — nothing more

## Prerequisites

- **Node.js:** Version 18 or higher is required
- **npm:** Included with Node.js installation

## Environment Variables

To run this example, you need to set the following environment variables:

- `USE_COMPUTER_API_KEY`: Required to control macOS sandboxes. Get it from [use.computer](https://use.computer)
- `USE_COMPUTER_RESERVATION_ID`: Required. The id of an active Mac Mini reservation to create the sandbox on — reserve one from the [use.computer dashboard](https://use.computer) (see [Reserving a Mac Mini](#reserving-a-mac-mini) below)
- `ANTHROPIC_API_KEY`: Required for Anthropic API access. Get it from the [Anthropic Console](https://console.anthropic.com/)

Create a `.env` file in the project directory with these variables (see `.env.example`).

## Getting Started

### Reserving a Mac Mini

macOS sandboxes run on dedicated Mac Minis reserved through use.computer — reservations run 24 hours or more and each Mac can host up to 2 macOS sandboxes at once. A reservation is billed for its full duration, so this script expects one to already exist rather than creating (and re-billing) a new one on every run.

1. Sign up at [use.computer](https://use.computer) (a starter credit is included, no card required) and grab your API key from **Settings**.
2. From the [use.computer dashboard](https://use.computer), reserve a Mac Mini and copy its reservation id.
3. Put both values in your `.env` file as `USE_COMPUTER_API_KEY` and `USE_COMPUTER_RESERVATION_ID`.

Reserving is also possible directly from code instead of the dashboard — it's a single SDK call:

```typescript
const reservation = await computer.reserve({ hours: 24 })
```

See the [use.computer Quick Start](https://docs.use.computer/docs/quickstart) for the full snippet and reservation options.

### Setup and Run

1. Install dependencies:

   ```bash
   npm install
   ```

2. Run the example:

   ```bash
   npm run start
   ```

Reserving a Mac Mini and running a macOS sandbox on use.computer incurs cost on your account — see [use.computer pricing](https://use.computer) before running this repeatedly.

## How It Works

1. A macOS sandbox is created on your existing reservation via `use-computer-sdk`
2. Screen recording is started on the sandbox
3. An LLM call generates an AppleScript based on the task description
4. The AppleScript is uploaded to the sandbox and run with `osascript`
5. The recording is stopped, downloaded, and saved as `recording.mp4`
6. The sandbox is closed

## Configuration

### Task Customization

The task is configured in the `task` variable in `index.ts`:

```typescript
const task = 'Open TextEdit, create a new document, and type a haiku about cloud computing.'
```

You can change this to any task that can be scripted with AppleScript, such as opening Safari, using Finder, or interacting with other native apps.

### Anthropic Model Configuration

By default, the example uses the following model, as specified in `index.ts`:

```typescript
const MODEL = 'claude-opus-5'
```

See [Models](https://docs.anthropic.com/en/docs/about-claude/models) for all supported models.

## Example Output

When the script completes, you'll see output similar to:

```
Creating a macOS sandbox...
Sandbox ready. Watch it live at: https://api.use.computer/vnc?sandbox=sb-59278e445d893dcb2a4510e62b3b0e6b&token=***
Recording started: rec-94865f9d65a94aa4
Task: Open TextEdit, create a new document, and type a haiku about cloud computing.
Generating AppleScript...
-- Open TextEdit, create a new document, and type a haiku about cloud computing

tell application "TextEdit"
	activate
	delay 1.5
end tell

tell application "System Events"
	tell process "TextEdit"
		-- Create a new document (Cmd+N)
		keystroke "n" using command down
		delay 1.5

		-- Type the haiku, line by line
		keystroke "Servers in the mist,"
		delay 0.5
		key code 36 -- Return
		delay 0.3

		keystroke "my data drifts far from home—"
		delay 0.5
		key code 36 -- Return
		delay 0.3

		keystroke "the sky holds my files."
		delay 0.5
	end tell
end tell
Running AppleScript...
Output: (no output)
Stopping recording...
✓ Recording saved to recording.mp4
```

Open `recording.mp4` to watch TextEdit open and the haiku get typed out in the sandbox.

## License

See the main project LICENSE file for details.

## References

- [use.computer Documentation](https://docs.use.computer)
- [use.computer Quick Start](https://docs.use.computer/docs/quickstart)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Daytona Documentation](https://www.daytona.io/docs)
