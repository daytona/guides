# iOS Xcode Simulator Builder (Anthropic + use.computer)

## Overview

This example demonstrates using an LLM to write both the source and the tests for a small iOS app, then building and verifying it end-to-end inside a real macOS sandbox. It uses [use.computer](https://use.computer) to provision a macOS sandbox, and the [Anthropic API](https://www.anthropic.com/api) to generate a SwiftUI view and its XCTest unit tests from a plain-English description.

In this example, the script asks Claude to write a simple counter app (and a test for its counting logic), assembles a real Xcode project around that code with [XcodeGen](https://github.com/yonaskolb/XcodeGen), builds it, installs and runs it on the iOS Simulator via `simctl`, runs the test suite, and prints a parsed pass/fail summary.

## Features

- **Real macOS sandbox:** Created on your use.computer reservation, torn down when the script finishes
- **Natural language interface:** Describe the app in plain English; Claude writes the SwiftUI view and its unit tests
- **Real Xcode project, built from scratch:** [XcodeGen](https://github.com/yonaskolb/XcodeGen) turns a project spec into an `.xcodeproj` at runtime — nothing is checked into this repo
- **Runs on the actual iOS Simulator:** Installed and launched with `xcrun simctl`, not just compiled
- **Automated test run with parsed results:** `xcodebuild test` output is parsed into a clean pass/fail summary, with a non-zero exit code on failure
- **Screenshot for manual verification:** A full-screen screenshot of the sandbox is downloaded after launch, since the test suite proves the app's logic but not that its UI actually renders correctly
- **No agent loop:** One script, one LLM call, one build/test pipeline — nothing more

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

macOS sandboxes run on dedicated Mac Minis reserved through use.computer — reservations run 24 hours or more at $1.91/hour per Mac, billed for the full duration regardless of how many sandboxes you create with it, and each Mac can host up to 2 macOS sandboxes at once. This script expects a reservation to already exist rather than creating (and re-billing) a new one on every run.

1. Sign up at [use.computer](https://use.computer) (a starter credit is included, no card required) and grab your API key from **Settings**.
2. From the [use.computer dashboard](https://use.computer), reserve a Mac Mini and copy its reservation id.
3. Put both values in your `.env` file as `USE_COMPUTER_API_KEY` and `USE_COMPUTER_RESERVATION_ID`.

Reserving is also possible directly from code instead of the dashboard — it's a single SDK call:

```typescript
const reservation = await computer.reserve({ hours: 24 })
```

See the [use.computer Quick Start](https://docs.use.computer/docs/quickstart) for the full snippet and reservation options.

This example also assumes the Mac Mini image already has a full Xcode install (not just the Command Line Tools), Homebrew, and at least one iOS Simulator runtime. The script installs [XcodeGen](https://github.com/yonaskolb/XcodeGen) itself via `brew install xcodegen` if it isn't already present.

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

1. A macOS sandbox is created on your existing reservation via `use-computer-sdk`
2. An LLM call generates a SwiftUI `ContentView` and an XCTest case for the task description
3. The generated files, plus a static XcodeGen spec (`project.yml`) and app entry point, are uploaded to the sandbox
4. `xcodegen generate` turns the spec into a real `.xcodeproj`
5. An available iOS Simulator device is selected and booted with `xcrun simctl`
6. `xcodebuild` builds the app against that simulator
7. The built app is installed and launched on the simulator with `xcrun simctl install`/`launch`
8. A full-screen screenshot is captured and downloaded for manual visual verification
9. `xcodebuild test` runs the XCTest suite against the same simulator, writing a `.xcresult` bundle
10. The `.xcresult` bundle is zipped and downloaded, and the test output is parsed into a pass/fail summary printed to the console
11. The sandbox is closed

## Configuration

### Task Customization

The task is configured in the `task` variable in `index.ts`:

```typescript
const task =
  'Build a simple SwiftUI counter app: a number label in the center of the screen, with "+" and "-" buttons ' +
  'below it that increment and decrement the count by 1. The count must never go below zero -- the "-" button ' +
  'should have no effect at zero.'
```

You can change this to describe any small, self-contained SwiftUI app with testable logic — the LLM always outputs a `Sources/ContentView.swift` and a `Tests/CounterAppTests.swift`.

### Xcode Project Configuration

The XcodeGen spec is defined in the `PROJECT_YML` constant in `index.ts`. It configures a `CounterApp` application target and a `CounterAppTests` unit test target, both with code signing disabled (not needed for simulator builds). Edit it to change the deployment target, add resources, or add more targets.

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
Task: Build a simple SwiftUI counter app: a number label in the center of the screen, with "+" and "-" buttons below it that increment and decrement the count by 1. The count must never go below zero -- the "-" button should have no effect at zero.
Generating app and test source...
Uploading project files...
Ensuring xcodegen is installed...
Generating Xcode project...
Selecting an iOS simulator...
Using simulator: iPhone 15 (12345678-ABCD-1234-ABCD-1234567890AB)
Booting simulator...
Building app...
Installing app on simulator...
Launching app on simulator...
Capturing screenshot...
✓ Screenshot saved to screenshot.png
Running tests...
Archiving test results...
✓ Test results saved to TestResults.xcresult.zip

Test Results
============
[PASS] CounterAppTests.testIncrement (0.001s)
[PASS] CounterAppTests.testDecrementStopsAtZero (0.001s)
------------
SUCCEEDED: executed 2, 0 failures (0 unexpected), 0.003s
Closing sandbox...
```

Open `screenshot.png` to see the app running on the simulator, and unzip `TestResults.xcresult.zip` (or open it directly in Xcode) to inspect the full test report.

## License

See the main project LICENSE file for details.

## References

- [use.computer Documentation](https://docs.use.computer)
- [use.computer Quick Start](https://docs.use.computer/docs/quickstart)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)
- [xcodebuild documentation](https://developer.apple.com/documentation/xcode/building-and-running-an-app)
- [simctl documentation](https://developer.apple.com/documentation/xcode/running-your-app-in-simulator-or-on-a-device)
