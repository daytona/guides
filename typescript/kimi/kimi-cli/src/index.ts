/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Daytona, Sandbox } from '@daytona/sdk'
import * as dotenv from 'dotenv'
import * as readline from 'readline'
import { KimiSession } from './session.js'

dotenv.config()

async function main() {
  const apiKey = process.env.DAYTONA_API_KEY
  if (!apiKey) {
    console.error('Error: DAYTONA_API_KEY environment variable is not set')
    console.error('Create a .env file with your Daytona API key (see .env.example)')
    process.exit(1)
  }

  if (!process.env.SANDBOX_KIMI_API_KEY) {
    console.error('Error: SANDBOX_KIMI_API_KEY environment variable is not set')
    console.error('Get a Kimi API key from https://platform.kimi.ai/console/api-keys')
    process.exit(1)
  }

  const daytona = new Daytona({ apiKey })

  let sandbox: Sandbox | undefined
  let session: KimiSession | undefined

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
    // Inject the Kimi settings at create time so the CLI runs headless with no
    // browser login or device flow. The host-side SANDBOX_KIMI_API_KEY maps to the
    // bare KIMI_API_KEY the CLI expects inside the sandbox. All three variables are
    // required: with no config file present, the CLI builds its LLM provider entirely
    // from the environment, and it refuses to start a turn ("LLM not set") unless the
    // base URL and model name are also set.
    console.log('Creating sandbox...')
    sandbox = await daytona.create({
      envVars: {
        KIMI_API_KEY: process.env.SANDBOX_KIMI_API_KEY,
        KIMI_BASE_URL: 'https://api.moonshot.ai/v1',
        KIMI_MODEL_NAME: 'kimi-k3',
      },
    })

    process.once('SIGINT', () => cleanup())

    // pip's exit code is a reliable success signal, so it is asserted directly. The
    // version check uses the absolute path `$HOME/.local/bin/kimi` (where pip's user
    // install drops the entrypoint) so it does not depend on the sandbox shell's PATH.
    console.log('Installing Kimi CLI...')
    const install = await sandbox.process.executeCommand('pip install kimi-cli')
    if (install.exitCode !== 0) {
      throw new Error('Error installing Kimi CLI: ' + install.result)
    }
    const version = await sandbox.process.executeCommand('"$HOME/.local/bin/kimi" --version')
    if (version.exitCode !== 0) {
      throw new Error(
        'Kimi CLI did not install correctly.\n' +
          `Install output:\n${install.result}\n` +
          `Version check output:\n${version.result}`,
      )
    }

    console.log('Starting Kimi CLI...')
    session = new KimiSession(sandbox)
    await session.initialize()

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
