/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Computer, MacOSSandbox } from 'use-computer-sdk'
import type { ExecResult } from 'use-computer-sdk'
import * as dotenv from 'dotenv'
import * as fs from 'fs'

dotenv.config()

const APP_NAME = 'CounterApp'
const BUNDLE_ID = 'com.example.counterapp'
const REMOTE_ROOT = `~/${APP_NAME}`

// Static XcodeGen spec. It wires up an app target and a hosted unit-test target
// (dependencies: [{ target: APP_NAME }] gives the test target TEST_HOST/bundle-loader
// settings automatically, so `@testable import CounterApp` resolves).
const PROJECT_YML = `name: ${APP_NAME}
options:
  bundleIdPrefix: com.example
  deploymentTarget:
    iOS: "16.0"
targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: Sources
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: ${BUNDLE_ID}
        CODE_SIGNING_ALLOWED: NO
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
        MARKETING_VERSION: "1.0"
        CURRENT_PROJECT_VERSION: "1"
        TARGETED_DEVICE_FAMILY: "1"
        SWIFT_VERSION: "5.0"
  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: Tests
    dependencies:
      - target: ${APP_NAME}
    settings:
      base:
        CODE_SIGNING_ALLOWED: NO
        GENERATE_INFOPLIST_FILE: YES
        SWIFT_VERSION: "5.0"
schemes:
  ${APP_NAME}:
    build:
      targets:
        ${APP_NAME}: all
        ${APP_NAME}Tests: [test]
    test:
      targets:
        - ${APP_NAME}Tests
`

// Static app entry point.
const APP_ENTRY_SWIFT = `import SwiftUI

@main
struct ${APP_NAME}App: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
`

// Static app source: a counter view whose count never goes below zero. The counting logic
// lives in a plain `Counter` struct (rather than only inside @State) so it can be exercised
// directly by the XCTest case below via @testable import, without any UI testing.
const CONTENT_VIEW_SWIFT = `import SwiftUI

struct Counter {
    private(set) var value = 0

    mutating func increment() {
        value += 1
    }

    mutating func decrement() {
        if value > 0 {
            value -= 1
        }
    }
}

struct ContentView: View {
    @State private var counter = Counter()

    var body: some View {
        VStack(spacing: 24) {
            Text("\\(counter.value)")
                .font(.system(size: 64, weight: .bold))

            HStack(spacing: 40) {
                Button(action: { counter.decrement() }) {
                    Image(systemName: "minus.circle.fill")
                        .font(.system(size: 44))
                }

                Button(action: { counter.increment() }) {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 44))
                }
            }
        }
        .padding()
    }
}
`

// Static test source: exercises the Counter logic above.
const COUNTER_APP_TESTS_SWIFT = `import XCTest
@testable import ${APP_NAME}

final class ${APP_NAME}Tests: XCTestCase {
    func testIncrement() {
        var counter = Counter()
        counter.increment()
        XCTAssertEqual(counter.value, 1)
    }

    func testDecrementStopsAtZero() {
        var counter = Counter()
        counter.decrement()
        XCTAssertEqual(counter.value, 0)
    }

    func testIncrementThenDecrement() {
        var counter = Counter()
        counter.increment()
        counter.increment()
        counter.decrement()
        XCTAssertEqual(counter.value, 1)
    }
}
`

interface SimDevice {
  udid: string
  name: string
  state: string
  isAvailable: boolean
}
interface SimctlListOutput {
  devices: Record<string, SimDevice[]>
}

// Picks an available iPhone simulator from `simctl list devices`, preferring the newest installed iOS runtime
function pickSimulator(json: SimctlListOutput): { udid: string; name: string; runtime: string } {
  const runtimeIds = Object.keys(json.devices).filter((id) => id.includes('iOS'))

  runtimeIds.sort((a, b) => {
    const va = a.match(/iOS-(\d+)-(\d+)/)
    const vb = b.match(/iOS-(\d+)-(\d+)/)
    if (!va || !vb) return 0
    return Number(vb[1]) - Number(va[1]) || Number(vb[2]) - Number(va[2])
  })

  for (const runtimeId of runtimeIds) {
    const iphone = (json.devices[runtimeId] ?? []).find((d) => d.isAvailable && d.name.startsWith('iPhone'))
    if (iphone) return { udid: iphone.udid, name: iphone.name, runtime: runtimeId }
  }

  throw new Error(
    'No available iPhone simulator found on this sandbox. Run `xcrun simctl list runtimes` and ' +
      '`xcrun simctl list devicetypes` on the Mac Mini to see what is installed, then create one ' +
      'manually (e.g. `xcrun simctl create "iPhone" <devicetype-id> <runtime-id>`) before re-running.',
  )
}

interface TestCaseResult {
  className: string
  method: string
  status: 'passed' | 'failed'
  seconds: number
}
interface TestSummary {
  succeeded: boolean
  executed: number
  failures: number
  unexpected: number
  seconds: number
  cases: TestCaseResult[]
}

// Parses raw `xcodebuild test` stdout into a pass/fail summary. Deliberately not using
// `xcresulttool`'s JSON output here -- its schema changed significantly between Xcode 15
// and 16, and the sandbox's exact Xcode version isn't pinned.
function parseTestOutput(output: string): TestSummary {
  const caseRegex = /Test Case '-\[(\S+)\.(\S+) (\S+)\]' (passed|failed) \(([\d.]+) seconds\)\./g
  const cases: TestCaseResult[] = []
  let m: RegExpExecArray | null
  while ((m = caseRegex.exec(output)) !== null) {
    const [, , className, method, status, seconds] = m
    cases.push({ className, method, status: status as 'passed' | 'failed', seconds: Number(seconds) })
  }

  const summaryMatch = output.match(/Executed (\d+) tests?, with (\d+) failures? \((\d+) unexpected\) in ([\d.]+) seconds/)
  const overallMatch = output.match(/\*\* TEST (SUCCEEDED|FAILED) \*\*/)

  if (!summaryMatch || !overallMatch) {
    throw new Error(`Could not parse xcodebuild test output:\n${output.slice(-4000)}`)
  }

  const [, executed, failures, unexpected, seconds] = summaryMatch
  return {
    succeeded: overallMatch[1] === 'SUCCEEDED',
    executed: Number(executed),
    failures: Number(failures),
    unexpected: Number(unexpected),
    seconds: Number(seconds),
    cases,
  }
}

function printSummary(summary: TestSummary) {
  console.log('\nTest Results')
  console.log('============')
  for (const c of summary.cases) {
    console.log(`[${c.status === 'passed' ? 'PASS' : 'FAIL'}] ${c.className}.${c.method} (${c.seconds}s)`)
  }
  console.log('------------')
  console.log(
    `${summary.succeeded ? 'SUCCEEDED' : 'FAILED'}: executed ${summary.executed}, ${summary.failures} failures (${summary.unexpected} unexpected), ${summary.seconds}s`,
  )
}

// Runs a command over SSH, logging its output, and throws on failure unless `tolerate` says to ignore it
async function runRemote(
  mac: MacOSSandbox,
  command: string,
  opts: { tolerate?: (result: ExecResult) => boolean } = {},
): Promise<ExecResult> {
  const result = await mac.execSsh(command)
  if (result.stdout) console.log(result.stdout)
  if (result.stderr) console.error(result.stderr)
  if (result.exitCode !== 0 && !opts.tolerate?.(result)) {
    throw new Error(`Command failed (exit ${result.exitCode}): ${command}`)
  }
  return result
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

  console.log('Creating a macOS sandbox...')
  const mac = await computer.create({ type: 'macos', reservationId })
  console.log('Sandbox ready. Watch it live at:', mac.vncUrl)

  try {
    // Fail loudly and early if Xcode isn't on this image, rather than failing confusingly later
    await runRemote(mac, 'xcodebuild -version')

    // Upload the project scaffolding and app/test source into the sandbox
    console.log('Uploading project files...')
    await runRemote(mac, `mkdir -p ${REMOTE_ROOT}/Sources ${REMOTE_ROOT}/Tests`)
    await mac.upload(Buffer.from(PROJECT_YML), `${REMOTE_ROOT}/project.yml`)
    await mac.upload(Buffer.from(APP_ENTRY_SWIFT), `${REMOTE_ROOT}/Sources/${APP_NAME}App.swift`)
    await mac.upload(Buffer.from(CONTENT_VIEW_SWIFT), `${REMOTE_ROOT}/Sources/ContentView.swift`)
    await mac.upload(Buffer.from(COUNTER_APP_TESTS_SWIFT), `${REMOTE_ROOT}/Tests/${APP_NAME}Tests.swift`)

    // Generate the actual Xcode project from the spec
    console.log('Ensuring xcodegen is installed...')
    await runRemote(mac, 'command -v xcodegen >/dev/null 2>&1 || brew install xcodegen')
    console.log('Generating Xcode project...')
    await runRemote(mac, `cd ${REMOTE_ROOT} && xcodegen generate`)

    // Pick and boot an iOS simulator
    console.log('Selecting an iOS simulator...')
    const listResult = await runRemote(mac, 'xcrun simctl list devices available -j')
    const simulator = pickSimulator(JSON.parse(listResult.stdout))
    console.log(`Using simulator: ${simulator.name} (${simulator.udid})`)

    console.log('Booting simulator...')
    await runRemote(mac, `xcrun simctl boot ${simulator.udid}`, {
      tolerate: (r) => r.stderr.includes('current state: Booted'),
    })
    await runRemote(mac, `xcrun simctl bootstatus ${simulator.udid} -b`)

    // Build the app against that exact simulator
    console.log('Building app...')
    const destination = `platform=iOS Simulator,id=${simulator.udid}`
    await runRemote(
      mac,
      `cd ${REMOTE_ROOT} && xcodebuild -project ${APP_NAME}.xcodeproj -scheme ${APP_NAME} ` +
        `-configuration Debug -derivedDataPath build -destination '${destination}' build`,
    )

    // Install and launch it on the simulator via simctl
    const appPath = `${REMOTE_ROOT}/build/Build/Products/Debug-iphonesimulator/${APP_NAME}.app`
    console.log('Installing app on simulator...')
    await runRemote(mac, `xcrun simctl install ${simulator.udid} ${appPath}`)
    console.log('Launching app on simulator...')
    await runRemote(mac, `xcrun simctl launch ${simulator.udid} ${BUNDLE_ID}`)

    // Give the UI a moment to settle, then capture a screenshot. xcodebuild test (below)
    // proves the app's *logic* is correct; this screenshot is what actually confirms the
    // SwiftUI view rendered as intended, for manual review.
    await new Promise((resolve) => setTimeout(resolve, 2000))
    console.log('Capturing screenshot...')
    const screenshot = await mac.screenshot.takeFullScreen()
    fs.writeFileSync('screenshot.png', screenshot)
    console.log('✓ Screenshot saved to screenshot.png')

    // Run the XCTest suite against the same, already-booted simulator
    console.log('Running tests...')
    const testResult = await runRemote(
      mac,
      `cd ${REMOTE_ROOT} && xcodebuild -project ${APP_NAME}.xcodeproj -scheme ${APP_NAME} ` +
        `-configuration Debug -derivedDataPath build -destination '${destination}' ` +
        `-resultBundlePath TestResults.xcresult test`,
      { tolerate: () => true }, // xcodebuild exits non-zero when tests fail; we parse pass/fail ourselves below
    )

    // Archive and download the .xcresult bundle as a structured artifact alongside the printed summary
    console.log('Archiving test results...')
    await runRemote(mac, `cd ${REMOTE_ROOT} && zip -r TestResults.xcresult.zip TestResults.xcresult`)
    const xcresultZip = await mac.download(`${REMOTE_ROOT}/TestResults.xcresult.zip`)
    fs.writeFileSync('TestResults.xcresult.zip', xcresultZip)
    console.log('✓ Test results saved to TestResults.xcresult.zip')

    // Parse and print a clean pass/fail summary
    const summary = parseTestOutput(testResult.stdout)
    printSummary(summary)
    if (!summary.succeeded) process.exitCode = 1
  } catch (error) {
    console.error('Error executing example:', error)
    process.exitCode = 1
  } finally {
    // Always tear down the sandbox
    console.log('Closing sandbox...')
    await mac.close()
  }
}

run()
