/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Daytona } from '@daytona/sdk'
import { Sandbox } from '@daytona/sdk/v0'
import * as dotenv from 'dotenv'
import * as readline from 'readline'
import { KiroSession } from './session.js'

dotenv.config()

async function main() {
  const apiKey = process.env.DAYTONA_API_KEY
  if (!apiKey) {
    console.error('Error: DAYTONA_API_KEY environment variable is not set')
    console.error('Create a .env file with your Daytona API key (see .env.example)')
    process.exit(1)
  }

  const daytona = new Daytona({ apiKey })

  let sandbox: Sandbox | undefined
  let session: KiroSession | undefined

  const cleanup = async (exitCode = 0) => {
    try {
      console.log('\nCleaning up...')
      if (session) await session.cleanup()
      if (sandbox) await sandbox.delete()
    } catch (e) {
      console.error('Error during cleanup:', e)
    } finally {
      process.exit(exitCode)
    }
  }

  try {
    console.log('Creating sandbox...')
    sandbox = await daytona.v0.create()

    process.once('SIGINT', () => cleanup())

    // The installer prints a colored, TTY-oriented summary and can exit non-zero in a
    // non-interactive shell even when the binary installed fine, so its exit code is
    // ignored. The version check uses the absolute path `$HOME/.local/bin/kiro-cli` so
    // it does not depend on the sandbox shell's PATH, and the install's combined
    // stdout+stderr is surfaced on failure for diagnostics.
    console.log('Installing Kiro CLI...')
    const install = await sandbox.process.executeCommand('curl -fsSL https://cli.kiro.dev/install | bash 2>&1')
    const version = await sandbox.process.executeCommand('"$HOME/.local/bin/kiro-cli" --version')
    if (version.exitCode !== 0) {
      throw new Error(
        'Kiro CLI did not install correctly.\n' +
          `Install output:\n${install.result}\n` +
          `Version check output:\n${version.result}`,
      )
    }

    console.log('Starting Kiro CLI...')
    session = new KiroSession(sandbox)
    await session.initialize()

    console.log('\nLog in to Kiro to continue (any plan works, including the free tier).')
    console.log('Pick a provider, open the URL that appears below, and approve the sign-in in your browser.\n')
    await session.login()

    const rl = readline.createInterface({ input: process.stdin, output: process.stdout })
    rl.once('SIGINT', () => cleanup())

    console.log('\nAgent ready. Press Ctrl+C at any time to exit.\n')

    while (true) {
      const prompt = await new Promise<string>((resolve) => rl.question('User: ', resolve))
      if (prompt.trim()) {
        await session.processPrompt(prompt)
      }
    }
  } catch (error) {
    console.error(error)
    await cleanup(1)
  }
}

main().catch(console.error)
