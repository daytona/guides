# iOS Code Signing (Anthropic + use.computer)

## Overview

This example demonstrates how to generate a real Xcode project on a macOS sandbox, sign it with your own Apple Developer Program credentials, and export a signed `.ipa` you can download to your machine. It uses [use.computer](https://use.computer) to provision a macOS sandbox, and the [Anthropic API](https://www.anthropic.com/api) to generate the Swift source for a tiny app.

In this example, the script asks Claude to write the SwiftUI view for a small counter app, turns it into a real Xcode project with [XcodeGen](https://github.com/yonaskolb/XcodeGen), archives and signs it for a real device using an **App Store Connect API key** (no Apple ID login, no 2FA — the standard non-interactive signing approach used by CI systems), exports a signed `.ipa`, and downloads it to your machine.

This guide is specifically about the code signing step — it does not run the app in the Simulator or on a device, and does not run tests.

## Features

- **Real macOS sandbox:** Created on your use.computer reservation, torn down when the script finishes
- **Natural language interface:** Describe the app in plain English; Claude writes the SwiftUI source
- **Real Xcode project:** [XcodeGen](https://github.com/yonaskolb/XcodeGen) turns the generated source into an actual `.xcodeproj`
- **Non-interactive code signing:** Signs with an App Store Connect API key — no Apple ID login, no 2FA, fully scriptable
- **Signed artifact:** The exported, signed `.ipa` is downloaded to your machine, and its signature is verified in the sandbox before download
- **No agent loop:** One script, one LLM call, one signing pipeline — nothing more

## Prerequisites

- **Node.js:** Version 18 or higher is required
- **npm:** Included with Node.js installation
- **Apple Developer Program membership:** App Store Connect API keys require a paid membership ($99/year) — a free Apple ID account cannot generate one

## Environment Variables

To run this example, you need to set the following environment variables:

- `USE_COMPUTER_API_KEY`: Required to control macOS sandboxes. Get it from [use.computer](https://use.computer)
- `USE_COMPUTER_RESERVATION_ID`: Required. The id of an active Mac Mini reservation to create the sandbox on — reserve one from the [use.computer dashboard](https://use.computer) (see [Reserving a Mac Mini](#reserving-a-mac-mini) below)
- `ANTHROPIC_API_KEY`: Required for Anthropic API access. Get it from the [Anthropic Console](https://console.anthropic.com/)
- `APPLE_TEAM_ID`: Required. Your Apple Developer Program Team ID (see [Getting your Apple credentials](#getting-your-apple-credentials) below)
- `APPLE_BUNDLE_ID`: Required. The bundle identifier to sign the app as, e.g. `com.yourteam.SignDemo`
- `APPLE_API_KEY_ID`: Required. The Key ID of your App Store Connect API key
- `APPLE_API_ISSUER_ID`: Required. The Issuer ID shown on the App Store Connect API Keys page
- `APPLE_API_KEY_PATH`: Required. Local path to the downloaded `AuthKey_<APPLE_API_KEY_ID>.p8` file. **Never commit this file** — it's already excluded via `.gitignore`
- `APPLE_EXPORT_METHOD`: Optional. `development` (default) or `ad-hoc` — see [Export method](#export-method) below

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

### Getting your Apple credentials

1. **Team ID:** Sign in to the [Apple Developer portal](https://developer.apple.com/account) → **Membership** → copy your **Team ID** (a 10-character alphanumeric string).
2. **App Store Connect API key:** Sign in to [App Store Connect](https://appstoreconnect.apple.com/) → **Users and Access** → **Integrations** → **App Store Connect API** → generate a new key with **Developer** (or higher) access.
   - Apple lets you download the `.p8` private key file **exactly once** — save it somewhere safe outside the repo.
   - Note the **Key ID** and **Issuer ID** shown on that page.
3. Put the Team ID, Key ID, Issuer ID, and the local path to the `.p8` file into your `.env` file as `APPLE_TEAM_ID`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`, and `APPLE_API_KEY_PATH`.
4. Pick a bundle identifier you're free to use under your team (e.g. `com.yourteam.SignDemo`) and set it as `APPLE_BUNDLE_ID`. With automatic signing and `-allowProvisioningUpdates`, Xcode will register it for you if it doesn't already exist.

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
2. An LLM call generates the SwiftUI source for `ContentView.swift` based on the task description
3. That file, plus static boilerplate (an XcodeGen `project.yml` spec and the `@main` app entry file — never touched by the LLM), are uploaded to the sandbox
4. `xcodegen generate` turns those files into a real `.xcodeproj`
5. The App Store Connect API key (`.p8`) is uploaded to the sandbox — this is what lets `xcodebuild` sign non-interactively
6. `xcodebuild archive` builds the app for a real device (`generic/platform=iOS`) with automatic signing, using `-allowProvisioningUpdates` plus the API key so Xcode fetches or creates the needed certificate and provisioning profile from Apple on the fly
7. `xcodebuild -exportArchive` exports a signed `.ipa` from the archive, using the same API key
8. The signature is verified in the sandbox with `codesign --display --verbose=4` and printed, so you can see the signing identity and team before downloading anything
9. The signed `.ipa` is downloaded to your machine as `SignDemo.ipa`
10. The sandbox is closed

## Configuration

### Task Customization

The app is described in the `task` variable in `index.ts`:

```typescript
const task = 'A minimal SwiftUI view showing a counter with + and - buttons, clamped so it never goes below zero.'
```

You can change this to describe any single-view SwiftUI app.

### Export method

Set via `APPLE_EXPORT_METHOD` in `.env`:

- `development` (default): signs with a development certificate/profile. Works with any Apple Developer Program team; doesn't require registering any devices to produce the signed `.ipa` itself (you'd only need a registered device to actually install it).
- `ad-hoc`: signs for distribution to a fixed list of registered test devices. Requires those devices' UDIDs to already be registered with your team.

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
Task: A minimal SwiftUI view showing a counter with + and - buttons, clamped so it never goes below zero.
Generating Swift source...
import SwiftUI

struct ContentView: View {
    @State private var count = 0

    var body: some View {
        VStack(spacing: 20) {
            Text("\(count)")
                .font(.largeTitle)
            HStack(spacing: 20) {
                Button("-") { count = max(0, count - 1) }
                Button("+") { count += 1 }
            }
        }
        .padding()
    }
}
Uploading project files...
Generating Xcode project with xcodegen...
Generated project at SignDemo.xcodeproj
Uploading App Store Connect API key...
Archiving and signing (this can take a minute)...
** ARCHIVE SUCCEEDED **
Exporting signed .ipa...
Exported SignDemo.ipa to build/export
Verifying code signature...
Executable=/private/var/.../unzipped/Payload/SignDemo.app/SignDemo
Identifier=com.yourteam.SignDemo
Authority=Apple Development: Jane Doe (ABCDE12345)
Authority=Apple Worldwide Developer Relations Certification Authority
Authority=Apple Root CA
TeamIdentifier=ABCDE12345
Downloading signed .ipa...
✓ Signed app saved to SignDemo.ipa
```

`SignDemo.ipa` is a real, signed build — inspect it with `codesign --display --verbose=4 SignDemo.ipa` locally, or install it on a registered device with a tool like [ios-deploy](https://github.com/ios-control/ios-deploy) or Xcode's Devices window.

## License

See the main project LICENSE file for details.

## References

- [use.computer Documentation](https://docs.use.computer)
- [use.computer Quick Start](https://docs.use.computer/docs/quickstart)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)
- [Apple: Distributing your app using the App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi)
