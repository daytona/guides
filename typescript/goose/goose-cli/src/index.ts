/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Daytona, Sandbox } from '@daytona/sdk'
import * as dotenv from 'dotenv'
import * as readline from 'readline'
import { GooseSession } from './session.js'

dotenv.config()

function formatCommandPreview(input: string, maxLength = 80): string {
  const normalized = input.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized
}

async function main() {
  const apiKey = process.env.DAYTONA_API_KEY
  if (!apiKey) {
    console.error('Error: DAYTONA_API_KEY environment variable is not set')
    console.error('Create a .env file with your Daytona API key (see .env.example)')
    process.exit(1)
  }

  if (!process.env.SANDBOX_OPENAI_API_KEY) {
    console.error('Error: SANDBOX_OPENAI_API_KEY environment variable is not set')
    console.error('Get an OpenAI API key from https://platform.openai.com/api-keys')
    process.exit(1)
  }

  const daytona = new Daytona({ apiKey })

  let sandbox: Sandbox | undefined
  let session: GooseSession | undefined
  const serverSessions: string[] = []

  const cleanup = async (exitCode = 0) => {
    try {
      console.log('\nCleaning up...')
      if (session) await session.cleanup()
      if (sandbox) {
        await Promise.allSettled(serverSessions.map((id) => sandbox!.process.deleteSession(id)))
        await sandbox.delete()
      }
    } catch (e) {
      console.error('Error during cleanup:', e)
    } finally {
      process.exit(exitCode)
    }
  }

  try {
    // Inject the OpenAI key and a fixed provider/model at create time, since a fresh
    // sandbox has no `goose configure` history - without these, `goose run` would
    // fall back to an interactive setup wizard, which can't be answered headlessly.
    // GOOSE_MODE=auto approves tool calls automatically (otherwise each one would
    // block waiting for a confirmation we have no way to answer). GOOSE_DISABLE_KEYRING
    // avoids Goose trying to reach a desktop keyring service that doesn't exist in the
    // sandbox, falling back to file-based secret storage instead.
    console.log('Creating sandbox...')
    sandbox = await daytona.create({
      envVars: {
        OPENAI_API_KEY: process.env.SANDBOX_OPENAI_API_KEY,
        GOOSE_PROVIDER: 'openai',
        GOOSE_MODEL: 'gpt-4o',
        GOOSE_MODE: 'auto',
        GOOSE_DISABLE_KEYRING: '1',
      },
    })

    const activeSandbox = sandbox

    process.once('SIGINT', () => cleanup())

    console.log('Installing Goose CLI...')
    // CONFIGURE=false skips the installer's trailing `goose configure` step. Without
    // it, the script tries to run that interactively - `[ -r /dev/tty ]` reports true
    // in the sandbox's exec environment even though there is no real controlling
    // terminal attached, so the read fails instead of falling back cleanly.
    const install = await activeSandbox.process.executeCommand(
      'curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false bash',
    )
    if (install.exitCode !== 0) {
      throw new Error('Error installing Goose CLI: ' + install.result)
    }

    // Daytona-aware system prompt, passed to Goose via its native --system flag.
    // We ask Goose to write server commands to start.sh instead of running them,
    // because `goose run` is a one-shot blocking command per turn: a foreground dev
    // server would never exit, so the turn (and the whole prompt loop) would hang.
    const previewLink = await activeSandbox.getPreviewLink(1234)
    const previewUrlPattern = previewLink.url.replace(/1234/, '{PORT}')
    const defaultSystemPrompt = [
      'You are running in a Daytona sandbox.',
      `When running services on localhost, they will be accessible as: ${previewUrlPattern}`,
      'When you need to start a server, DO NOT run it directly.',
      'Instead, write only the server start command to /home/daytona/start.sh (one command, no markdown).',
      'After writing the start command, provide the preview URL to the user.',
    ].join(' ')

    console.log('Starting Goose CLI...\n')
    session = new GooseSession(activeSandbox)
    await session.initialize({ systemPrompt: defaultSystemPrompt })

    const startServerFromScript = async () => {
      // Only run when Goose has produced a start script for this turn.
      const startScriptCheck = await activeSandbox.process.executeCommand('test -f /home/daytona/start.sh')
      if (startScriptCheck.exitCode !== 0) {
        return
      }

      const startScriptContents = (await activeSandbox.fs.downloadFile('/home/daytona/start.sh')).toString('utf-8')
      const clippedStartScript = formatCommandPreview(startScriptContents)
      console.log(`Running \`${clippedStartScript}\` via session command...`)
      // Execute server startup outside Goose so long-running/background commands
      // do not keep the turn (and `goose run`) from completing.
      const sessionId = `goose-server-session-${Date.now()}`
      await activeSandbox.process.createSession(sessionId)
      serverSessions.push(sessionId)

      await activeSandbox.process.executeSessionCommand(sessionId, {
        command: 'cd /home/daytona && chmod +x start.sh && ./start.sh',
        runAsync: true,
      })
    }

    const rl = readline.createInterface({ input: process.stdin, output: process.stdout })
    rl.once('SIGINT', () => cleanup())

    console.log('Agent ready. Press Ctrl+C at any time to exit.\n')

    while (true) {
      const prompt = await new Promise<string>((resolve) => rl.question('User: ', resolve))
      if (prompt.trim()) {
        await session.processPrompt(prompt)
        await startServerFromScript()
      }
    }
  } catch (error) {
    console.error(error)
    await cleanup(1)
  }
}

main().catch(console.error)
