import { Daytona } from '@daytona/sdk'
import { pathToFileURL } from 'node:url'

// Public API evidence: https://registry.npmjs.org/@daytona/sdk/2.0.0-alpha.4
// Targets @daytona/sdk 2.0.0-alpha.4. Requires v2 Linux access.
export async function runWorkflow(daytona: Daytona, image: string) {
  const sandbox = await daytona.v2.create(image, {
    waitSeconds: 60,
    createTimeoutSeconds: 300,
    lifecyclePolicy: { timeoutSeconds: 600, onTimeout: 'delete' },
  })
  // Keep the owned ID for recovery if the controller or cleanup fails.
  console.error(`Created disposable sandbox ${sandbox.id}`)
  try {
    // create's caller wait can expire before startup. Sandbox.wait uses seconds.
    await sandbox.wait({ until: 'started', timeout: 300 })
    const input = 'migration ok\n'
    await sandbox.fs.writeText('/tmp/migration-input.txt', input)
    const result = await sandbox.process.run({
      argv: ['python3', '-c',
        'from pathlib import Path; p=Path("/tmp/migration-input.txt"); Path("/tmp/migration-output.txt").write_bytes(p.read_bytes())'],
    }, { executionTimeout: 30_000 })
    if (result.reason !== 'exited' || result.exitCode !== 0) {
      throw new Error(`Command did not succeed: ${result.reason}, exit=${result.exitCode}`)
    }
    const output = await sandbox.fs.readText('/tmp/migration-output.txt')
    if (output !== input) throw new Error('File round-trip did not preserve the content')
    return { output, exitCode: result.exitCode }
  } finally {
    // Only the newly created disposable sandbox belongs to this example.
    // Deletion is asynchronous; returning does not prove teardown completed.
    await sandbox.delete()
  }
}

async function main() {
  if (!process.argv.includes('--run')) {
    throw new Error('Pass --run to create a billable disposable sandbox.')
  }
  const image = process.env.DAYTONA_IMAGE
  if (!image || !process.env.DAYTONA_API_KEY) {
    throw new Error('Export DAYTONA_API_KEY and DAYTONA_IMAGE (a registered image with python3).')
  }
  const daytona = new Daytona()
  try {
    console.log(JSON.stringify(await runWorkflow(daytona, image)))
  } finally {
    await daytona.close()
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1 })
}
