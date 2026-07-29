/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import 'dotenv/config'
import { Daytona } from '@daytona/sdk'
import type { Sandbox } from '@daytona/sdk'
import { randomBytes } from 'crypto'
import { readFileSync } from 'fs'
import { join } from 'path'
import { fileURLToPath } from 'url'
import { deepMerge, readEnvFile } from './utils.js'

// Constants
const OPENCLAW_PORT = 18789 // OpenClaw Gateway and Control UI port (loopback only)
const LOCAL_PROXY_PORT = 18790 // In-sandbox pairing proxy; the preview URL targets this port
const SHOW_LOGS = true // Stream OpenClaw stdout/stderr to the terminal
// Keep the sandbox private: the preview URL then requires Daytona
// authentication, so the gateway token is not the only thing standing between
// the internet and your assistant.
const MAKE_PUBLIC = false
const PERSIST_SANDBOX = true // Keep the sandbox running after the script exits
const DAYTONA_SNAPSHOT = 'daytona-medium' // This snapshot has openclaw installed

// Paths
const USER_CONFIG_PATH = join(process.cwd(), 'openclaw.json')
const ENV_SANDBOX_PATH = join(process.cwd(), '.env.sandbox')
// Resolved relative to this module so it works from any working directory.
const LOCAL_PROXY_SCRIPT_PATH = fileURLToPath(new URL('./local-pairing-proxy.cjs', import.meta.url))

// Global variables
let currentSandbox: Sandbox | null = null
let sandboxDeleted = false

// Shutdown the sandbox
// `forceDelete` is used when startup failed: PERSIST_SANDBOX means "keep my
// working assistant running", but a sandbox that never produced a link is
// unusable, and auto-stop is disabled, so it would run until deleted by hand.
async function shutdown(exitCode = 0, forceDelete = false) {
  if (sandboxDeleted) return
  sandboxDeleted = true
  if (!PERSIST_SANDBOX || forceDelete) {
    console.log('\nShutting down sandbox...')
    try {
      await currentSandbox?.delete(30)
    } catch (e) {
      console.error(e)
    }
  } else {
    // Sandboxes are created with auto-stop disabled, so surface the id: a
    // sandbox left behind here keeps running until it is deleted.
    console.log(`\nSandbox left running${currentSandbox ? ` (${currentSandbox.id})` : ''}.`)
  }
  process.exit(exitCode)
}

// OpenClaw config to run in a Daytona sandbox. The gateway binds loopback
// only: the sole exposed entrance is the local pairing proxy in front of it.
const OPENCLAW_CONFIG = {
  gateway: {
    mode: 'local' as const,
    port: OPENCLAW_PORT,
    bind: 'loopback' as const,
    auth: { mode: 'token' as const, token: '' },
  },
  agents: {
    defaults: {
      workspace: '~/.openclaw/workspace',
    },
  },
}

const GATEWAY_READY_TIMEOUT_MS = 90_000 // Per-attempt readiness budget
const GATEWAY_START_ATTEMPTS = 3

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// Start the gateway and wait until it answers on OPENCLAW_PORT. The first
// command in a freshly created sandbox can occasionally exit before the
// runtime is fully ready, so retry instead of failing the whole run.
async function startGatewayUntilReady(sandbox: Sandbox, sessionId: string): Promise<string> {
  for (let attempt = 1; attempt <= GATEWAY_START_ATTEMPTS; attempt++) {
    const { cmdId } = await sandbox.process.executeSessionCommand(sessionId, {
      command: 'openclaw gateway run',
      runAsync: true,
    })
    const deadline = Date.now() + GATEWAY_READY_TIMEOUT_MS
    let exited = false
    while (Date.now() < deadline) {
      await sleep(3000)
      const probe = await sandbox.process.executeCommand(
        `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${OPENCLAW_PORT}`,
      )
      if (probe.result?.trim() === '200') {
        return cmdId!
      }
      const session = await sandbox.process.getSession(sessionId)
      const command = session.commands?.find((c) => c.id === cmdId)
      if (command?.exitCode != null) {
        exited = true
        break
      }
    }
    // Only retry a command that actually exited. A gateway that is still
    // running owns OPENCLAW_PORT, so starting a second one would fail with
    // EADDRINUSE and leave us tracking the wrong command id.
    if (!exited) {
      throw new Error('OpenClaw gateway started but never became ready')
    }
    console.log(`Gateway start attempt ${attempt} exited before becoming ready, retrying...`)
  }
  throw new Error('OpenClaw gateway failed to start')
}

// OpenClaw pairs every new browser/device before it may use the Control UI -
// but it silently auto-approves pairing for clean LOCAL connections (loopback
// peer, no forwarded identity headers) once gateway token auth has succeeded.
// Daytona's preview proxy adds X-Forwarded-For, which makes browsers look
// remote and forces a manual approval step. The proxy script below strips those
// headers inside the sandbox, so preview visitors are treated as local and pair
// silently on their first attempt. Token auth still applies before pairing: the
// tokenized preview URL remains the secret that gates access.
// See src/local-pairing-proxy.cjs for the implementation and its trade-offs.
async function startLocalPairingProxy(sandbox: Sandbox, home: string): Promise<void> {
  const remotePath = `${home}/.openclaw-local-proxy.cjs`
  await sandbox.fs.uploadFile(LOCAL_PROXY_SCRIPT_PATH, remotePath)
  const sessionId = 'openclaw-local-proxy'
  await sandbox.process.createSession(sessionId)
  await sandbox.process.executeSessionCommand(sessionId, {
    command: `node ${remotePath} ${LOCAL_PROXY_PORT} ${OPENCLAW_PORT}`,
    runAsync: true,
  })
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    await sleep(1000)
    const probe = await sandbox.process.executeCommand(
      `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${LOCAL_PROXY_PORT}`,
    )
    if (probe.result?.trim() === '200') return
  }
  throw new Error('Local pairing proxy failed to start')
}

// Resolve when the gateway command actually exits. Polls the session command
// status instead of relying on the log stream, which can close early while the
// gateway keeps running.
async function waitForGatewayExit(sandbox: Sandbox, sessionId: string, cmdId: string): Promise<void> {
  for (;;) {
    await sleep(5000)
    try {
      const session = await sandbox.process.getSession(sessionId)
      const command = session.commands?.find((c) => c.id === cmdId)
      if (command?.exitCode != null) return
    } catch {
      // Transient control-plane error; keep watching.
    }
  }
}

// Main function
async function main() {
  // Create a new Daytona instance
  const daytona = new Daytona()

  // Create a new sandbox
  console.log('Creating Daytona sandbox...')
  const sandbox = await daytona.create({
    snapshot: DAYTONA_SNAPSHOT,
    autoStopInterval: 0,
    envVars: readEnvFile(ENV_SANDBOX_PATH),
    public: MAKE_PUBLIC,
  })
  currentSandbox = sandbox

  // Handle SIGINT
  process.on('SIGINT', () => shutdown())

  // Get the user home directory
  const home = await sandbox.getUserHomeDir()
  if (!home) throw new Error('Could not resolve the sandbox home directory')
  const openclawDir = `${home}/.openclaw`

  // Resolve the preview URL up front: its origin must be allowlisted so the
  // Gateway accepts browser connections coming through the Daytona proxy.
  // The preview targets the local pairing proxy port, not the gateway itself.
  const signed = await sandbox.getPreviewLink(LOCAL_PROXY_PORT)
  const previewOrigin = new URL(signed.url).origin

  // Read the user config and merge it with the base config
  const userConfig = JSON.parse(readFileSync(USER_CONFIG_PATH, 'utf8'))
  const baseConfig = deepMerge(OPENCLAW_CONFIG, userConfig)

  // Generate a random gateway token and add it to the config
  const gatewayToken = randomBytes(24).toString('hex')
  const config = deepMerge(baseConfig, {
    gateway: {
      auth: { mode: 'token' as const, token: gatewayToken },
      // Browser origin check: allow the preview URL origin explicitly.
      controlUi: { allowedOrigins: [previewOrigin] },
    },
  })

  // Write the config to the sandbox
  console.log('Configuring OpenClaw...')
  await sandbox.fs.createFolder(openclawDir, '755')
  await sandbox.fs.uploadFile(Buffer.from(JSON.stringify(config, null, 2), 'utf8'), `${openclawDir}/openclaw.json`)

  // Start the gateway and wait until it is ready
  const sessionId = 'openclaw-gateway'
  console.log('Starting OpenClaw...')
  await sandbox.process.createSession(sessionId)
  const cmdId = await startGatewayUntilReady(sandbox, sessionId)
  console.log(
    PERSIST_SANDBOX
      ? '(Ctrl+C to stop the script; the sandbox keeps running)'
      : '(Ctrl+C to shut down and delete the sandbox)',
  )

  // Start the local pairing proxy (see LOCAL_PROXY_SOURCE for why): browsers
  // arriving through the preview URL pair silently as local clients.
  await startLocalPairingProxy(sandbox, home)

  // Stream OpenClaw output for visibility. The stream can end on its own
  // (idle timeout, proxy reset) while the gateway keeps running, so it must
  // NOT drive shutdown - waitForGatewayExit owns lifecycle.
  if (SHOW_LOGS) {
    void sandbox.process
      .getSessionCommandLogs(
        sessionId,
        cmdId,
        (chunk) => process.stdout.write(chunk),
        (chunk) => process.stderr.write(chunk),
      )
      .catch(() => {
        // Ignore stream errors; waitForGatewayExit owns lifecycle.
      })
  }

  // Pass the token in the URL fragment: fragments are never sent to servers,
  // so the token stays out of proxy/access logs and Referer headers. The
  // Control UI reads it, applies it, and strips it from the address bar.
  const dashboardUrl = `${signed.url}#token=${gatewayToken}`

  console.log(`\n\x1b[1m🔗 Secret link to Control UI: ${dashboardUrl}\x1b[0m`)
  console.log('\nThe sandbox is private - open the link while signed in to Daytona.')
  console.log(`\nOpenClaw is ready.`)
  console.log('--------------------------------')

  // Keep the process (and the auto-approval loop) alive until the gateway
  // process exits or the user presses Ctrl+C - not tied to the log stream.
  await waitForGatewayExit(sandbox, sessionId, cmdId)
  await shutdown()
}

main().catch(async (err) => {
  console.error(err)
  // Startup never handed the user a working link, so delete the sandbox even
  // when PERSIST_SANDBOX is set - otherwise it lingers with auto-stop off.
  await shutdown(1, true)
})
