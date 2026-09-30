/*
 * Copyright 2026 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Daytona, Sandbox } from '@daytona/sdk'
import * as dotenv from 'dotenv'
import * as fs from 'fs'
import * as path from 'path'

dotenv.config()

const APP_DIR = '/home/daytona/anchor'

function requireEnv(name: string): string {
  const value = process.env[name]
  if (!value) {
    console.error(`Error: ${name} environment variable is not set`)
    console.error('Copy .env.example to .env and fill in your keys')
    process.exit(1)
  }
  return value
}

async function runChecked(sandbox: Sandbox, command: string, timeoutSeconds: number): Promise<string> {
  const response = await sandbox.process.executeCommand(command, APP_DIR, undefined, timeoutSeconds)
  const output = response.result?.trim() ?? ''
  if (output) console.log(output)
  if (response.exitCode) {
    throw new Error(`Command failed (${response.exitCode}): ${command}`)
  }
  return output
}

async function main() {
  const daytonaApiKey = requireEnv('DAYTONA_API_KEY')
  const anchorApiKey = requireEnv('ANCHOR_API_KEY')

  const daytona = new Daytona({ apiKey: daytonaApiKey })
  let sandbox: Sandbox | undefined

  try {
    console.log('Creating sandbox...')
    sandbox = await daytona.create({
      envVars: {
        ANCHOR_API_KEY: anchorApiKey,
        // Alias the name the SDK reads, so session and task calls authenticate
        // even when a script does not call setConfig or pass api_key.
        ANCHORBROWSER_API_KEY: anchorApiKey,
      },
    })

    console.log('Installing Anchor SDK in the sandbox...')
    await sandbox.fs.createFolder(APP_DIR, '755')
    const localDir = path.join(__dirname, '..', 'sandbox')
    for (const fileName of ['package.json', 'browse.ts']) {
      await sandbox.fs.uploadFile(fs.readFileSync(path.join(localDir, fileName)), `${APP_DIR}/${fileName}`)
    }

    // anchorbrowser depends on Playwright. Skip the local browser download:
    // Chromium runs in Anchor Cloud, not in this sandbox.
    await runChecked(sandbox, 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install', 300)
    await runChecked(sandbox, 'npx tsx browse.ts', 600)

    console.log('Done.')
  } catch (error) {
    console.error(error)
    process.exitCode = 1
  } finally {
    if (sandbox) {
      console.log('Deleting sandbox...')
      await sandbox.delete()
    }
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
