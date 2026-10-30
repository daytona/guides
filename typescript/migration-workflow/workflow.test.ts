import assert from 'node:assert/strict'
import test from 'node:test'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import type { Daytona } from '@daytona/sdk'
import { runWorkflow } from './workflow.js'

for (const scenario of [
  { name: 'successful round-trip', reason: 'exited', exitCode: 0, output: 'migration ok\n', succeeds: true },
  { name: 'nonzero exit', reason: 'exited', exitCode: 1, output: 'migration ok\n', succeeds: false },
  { name: 'wait did not finish', reason: 'timed_out', exitCode: 0, output: 'migration ok\n', succeeds: false },
  { name: 'corrupt output', reason: 'exited', exitCode: 0, output: 'different', succeeds: false },
]) test(`disposable workflow: ${scenario.name}`, async () => {
  let deleted = 0
  let ready = false
  const sandbox = {
    id: 'example-sandbox',
    async wait() { ready = true },
    fs: { async writeText() { assert.ok(ready, 'Wait for started before filesystem access') }, async readText() { return scenario.output } },
    process: { async run() { return { reason: scenario.reason, exitCode: scenario.exitCode } } },
    async delete() { deleted++ },
  }
  const client = { v2: { async create() { return sandbox } } } as unknown as Daytona
  if (scenario.succeeds) assert.equal((await runWorkflow(client, 'example-image')).output, 'migration ok\n')
  else await assert.rejects(runWorkflow(client, 'example-image'))
  assert.equal(deleted, 1, 'The owned sandbox must be cleaned up on success and failure')
})

test('startup failure cleans up without accessing the guest', async () => {
  let deleted = 0
  const client = { v2: { async create() { return {
    id: 'failed-start',
    async wait() { throw new Error('startup deadline exceeded') },
    async delete() { deleted++ },
  } } } } as unknown as Daytona
  await assert.rejects(runWorkflow(client, 'example-image'), /startup deadline exceeded/)
  assert.equal(deleted, 1)
})

test('CLI refuses cloud execution without --run', () => {
  const child = spawnSync(process.execPath, [fileURLToPath(new URL('./workflow.js', import.meta.url))], {
    encoding: 'utf8', env: { PATH: process.env.PATH },
  })
  assert.notEqual(child.status, 0)
  assert.match(child.stderr, /--run/)
})
