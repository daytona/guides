/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Computer, MacOSSandbox } from 'use-computer-sdk'
import * as dotenv from 'dotenv'
import * as fs from 'fs'

dotenv.config()

const REMOTE_DIR = '/tmp/SignDemo'

// ---- Static project files. Everything below is hardcoded — nothing is generated. ----

// xcodegen spec: turns the uploaded Swift files into a real .xcodeproj.
// PRODUCT_BUNDLE_IDENTIFIER and DEVELOPMENT_TEAM here are placeholders —
// the real values are passed on the xcodebuild command line, which overrides them.
const PROJECT_YML = `name: SignDemo
options:
  createIntermediateGroups: true
targets:
  SignDemo:
    type: application
    platform: iOS
    deploymentTarget: "16.0"
    sources:
      - SignDemo
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.example.SignDemo
        CODE_SIGN_STYLE: Automatic
        GENERATE_INFOPLIST_FILE: true
        INFOPLIST_KEY_UILaunchScreen_Generation: true
        MARKETING_VERSION: "1.0"
        CURRENT_PROJECT_VERSION: "1"
        SWIFT_VERSION: "5.0"
`

// @main entry point
const APP_ENTRY_SWIFT = `import SwiftUI

@main
struct SignDemoApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
`

// The app's single view — a counter with + and - buttons, clamped so it never goes below zero
const CONTENT_VIEW_SWIFT = `import SwiftUI

struct ContentView: View {
    @State private var count = 0

    var body: some View {
        VStack(spacing: 20) {
            Text("\\(count)")
                .font(.largeTitle)
            HStack(spacing: 20) {
                Button("-") { count = max(0, count - 1) }
                Button("+") { count += 1 }
            }
        }
        .padding()
    }
}
`

function exportOptionsPlist(teamId: string, method: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>${method}</string>
  <key>teamID</key>
  <string>${teamId}</string>
  <key>signingStyle</key>
  <string>automatic</string>
</dict>
</plist>
`
}

// Runs a command over SSH, streams its stdout, and throws on a non-zero exit code
async function sh(mac: MacOSSandbox, label: string, command: string, timeoutMs = 5 * 60 * 1000) {
  console.log(label)
  const exec = await mac.execSsh(command, timeoutMs)
  if (exec.stdout) console.log(exec.stdout)
  if (exec.exitCode !== 0) {
    throw new Error(`${label} failed (exit ${exec.exitCode}): ${exec.stderr}`)
  }
  return exec
}

// Make sure you have the USE_COMPUTER_API_KEY and USE_COMPUTER_RESERVATION_ID environment variables set
const computer = new Computer()

async function run() {
  // A reservation is billed for its full duration, so this script expects one to already exist
  // rather than creating (and re-billing) a new one on every run. See the README for how to reserve one.
  const reservationId = process.env.USE_COMPUTER_RESERVATION_ID
  if (!reservationId) {
    console.error('Error: USE_COMPUTER_RESERVATION_ID environment variable is not set')
    console.error('Reserve a Mac Mini (see README) and put its id in your .env file')
    process.exit(1)
  }

  // Signing needs a real Apple Developer Program team and an App Store Connect API key.
  // See the README for how to get each of these.
  const teamId = process.env.APPLE_TEAM_ID
  const bundleId = process.env.APPLE_BUNDLE_ID
  const keyId = process.env.APPLE_API_KEY_ID
  const issuerId = process.env.APPLE_API_ISSUER_ID
  const apiKeyPath = process.env.APPLE_API_KEY_PATH
  const exportMethod = process.env.APPLE_EXPORT_METHOD || 'development'
  if (!teamId || !bundleId || !keyId || !issuerId || !apiKeyPath) {
    console.error('Error: APPLE_TEAM_ID, APPLE_BUNDLE_ID, APPLE_API_KEY_ID, APPLE_API_ISSUER_ID, and APPLE_API_KEY_PATH must all be set')
    console.error('See the README for how to create an App Store Connect API key')
    process.exit(1)
  }
  if (!fs.existsSync(apiKeyPath)) {
    console.error(`Error: APPLE_API_KEY_PATH (${apiKeyPath}) does not exist`)
    process.exit(1)
  }

  let mac: MacOSSandbox | null = null

  try {
    // Create a macOS sandbox on the existing reservation
    console.log('Creating a macOS sandbox...')
    mac = await computer.create({ type: 'macos', reservationId })
    console.log('Sandbox ready. Watch it live at:', mac.vncUrl)

    // Upload the project sources and turn them into a real Xcode project
    console.log('Uploading project files...')
    await mac.execSsh(`mkdir -p ${REMOTE_DIR}/SignDemo`)
    await mac.upload(Buffer.from(PROJECT_YML), `${REMOTE_DIR}/project.yml`)
    await mac.upload(Buffer.from(APP_ENTRY_SWIFT), `${REMOTE_DIR}/SignDemo/SignDemoApp.swift`)
    await mac.upload(Buffer.from(CONTENT_VIEW_SWIFT), `${REMOTE_DIR}/SignDemo/ContentView.swift`)

    await sh(mac, 'Generating Xcode project with xcodegen...', `cd ${REMOTE_DIR} && xcodegen generate`)

    // Upload the App Store Connect API key used to authenticate xcodebuild — no Apple ID login, no 2FA
    console.log('Uploading App Store Connect API key...')
    const remoteKeyPath = `${REMOTE_DIR}/AuthKey_${keyId}.p8`
    await mac.upload(fs.readFileSync(apiKeyPath), remoteKeyPath)
    const authFlags = `-allowProvisioningUpdates -authenticationKeyPath ${remoteKeyPath} -authenticationKeyID ${keyId} -authenticationKeyIssuerID ${issuerId}`

    // Archive the app for a real device, signing it automatically via the API key
    await sh(
      mac,
      'Archiving and signing (this can take a minute)...',
      `cd ${REMOTE_DIR} && xcodebuild archive ` +
        `-project SignDemo.xcodeproj -scheme SignDemo -destination "generic/platform=iOS" ` +
        `-archivePath build/SignDemo.xcarchive ${authFlags} ` +
        `CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM=${teamId} PRODUCT_BUNDLE_IDENTIFIER=${bundleId}`,
      10 * 60 * 1000,
    )

    // Export a signed .ipa from the archive
    await mac.upload(Buffer.from(exportOptionsPlist(teamId, exportMethod)), `${REMOTE_DIR}/ExportOptions.plist`)
    await sh(
      mac,
      'Exporting signed .ipa...',
      `cd ${REMOTE_DIR} && xcodebuild -exportArchive ` +
        `-archivePath build/SignDemo.xcarchive -exportPath build/export ` +
        `-exportOptionsPlist ExportOptions.plist ${authFlags}`,
      5 * 60 * 1000,
    )

    // Verify the signature on the sandbox before downloading anything
    await sh(
      mac,
      'Verifying code signature...',
      `cd ${REMOTE_DIR}/build/export && rm -rf unzipped && unzip -o SignDemo.ipa -d unzipped && ` +
        `codesign --display --verbose=4 unzipped/Payload/*.app 2>&1`,
    )

    // Download the signed .ipa
    console.log('Downloading signed .ipa...')
    const ipaBytes = await mac.download(`${REMOTE_DIR}/build/export/SignDemo.ipa`)
    fs.writeFileSync('SignDemo.ipa', ipaBytes)
    console.log('✓ Signed app saved to SignDemo.ipa')
  } catch (error) {
    console.error('Error executing example:', error)
  } finally {
    // Always tear down the sandbox
    if (mac) {
      await mac.close()
    }
  }
}

run()
