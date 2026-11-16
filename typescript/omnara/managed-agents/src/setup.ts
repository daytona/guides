/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

// `npm run setup`: create the Omnara resources the demo uses. Anything that
// already exists is left as it is, so running this again only adds what's
// missing. To change the Daytona key or pool settings, run `npm run cleanup`
// first.

// Load OMNARA_API_KEY, DAYTONA_API_KEY, and OMNARA_ORG_ID from .env.
import 'dotenv/config'
import { readFile } from 'node:fs/promises'
import { Daytona } from '@daytona/sdk'
import type { OmnaraClient } from '@omnara/sdk'
import { ApiError, sdk } from '@omnara/sdk'
import { parse } from 'yaml'
import { AGENT_FILE, POOL_NAME, PROJECT_NAME, SECRET_NAME, pool } from './config.js'
import { findPool, findProject, findSecret, omnaraClient, resolveOrg } from './omnara.js'

// Read the model from agent.yaml, so setup can grant it to the project.
async function agentModel(): Promise<{ providerConfig: string; name: string }> {
  const parsed = parse(await readFile(AGENT_FILE, 'utf8')) as { model?: { provider_config?: string; name?: string } }
  const providerConfig = parsed?.model?.provider_config
  const name = parsed?.model?.name
  if (!providerConfig || !name) throw new Error(`${AGENT_FILE} must set model.provider_config and model.name`)
  return { providerConfig, name }
}

// Check the Daytona key with Daytona before storing it in Omnara, so a bad key
// fails here with a clear error.
async function checkDaytonaKey(apiKey: string): Promise<void> {
  try {
    await new Daytona({ apiKey }).v0.snapshot.get(pool.snapshot)
  } catch (err) {
    throw new Error(
      `Daytona didn't accept your API key or has no snapshot named "${pool.snapshot}": ` +
        (err instanceof Error ? err.message : String(err)),
    )
  }
}

// Omnara creates one Daytona sandbox per agent from this pool, using the key
// in the secret, and deletes it after it has been idle for deleteAfterIdleMinutes.
async function createPool(client: OmnaraClient, orgID: string, secretID: string) {
  const { data } = await sdk.createMachinePool({
    client,
    path: { orgID },
    body: {
      name: POOL_NAME,
      provider: 'daytona',
      description: 'Daytona sandboxes for the Daytona guide',
      provider_auth_secret_id: secretID,
      default_machine_provider_options: { snapshot: pool.snapshot, target: pool.target },
      max_total_machines: pool.maxTotalMachines,
      max_total_cpu: pool.maxTotalCpu,
      max_total_memory_mb: pool.maxTotalMemoryMb,
      max_machine_cpu: pool.maxMachineCpu,
      max_machine_memory_mb: pool.maxMachineMemoryMb,
      delete_after_idle_minutes: pool.deleteAfterIdleMinutes,
    },
  })
  return data
}

// The ID of the agent's model in the organization's model provider config.
async function configuredModelID(
  client: OmnaraClient,
  orgID: string,
  model: { providerConfig: string; name: string },
): Promise<string> {
  const { data: providers } = await sdk.listModelProviderConfigs({
    client,
    path: { orgID },
    query: { name: model.providerConfig },
  })
  const provider = providers.data.find((item) => item.name === model.providerConfig)
  if (!provider) throw new Error(`No model provider named "${model.providerConfig}" in this organization`)

  let cursor: string | undefined
  do {
    const { data } = await sdk.listConfiguredModels({
      client,
      path: { orgID, modelProviderConfigID: provider.id },
      query: { cursor },
    })
    const match = data.data.find((item) => item.name === model.name)
    if (match) return match.id
    cursor = data.next_cursor ?? undefined
  } while (cursor)
  throw new Error(`Model provider "${model.providerConfig}" has no model named "${model.name}"`)
}

// Pools and models belong to the organization; grants let the project use
// them. Omnara returns 409 if the project already has the grant.
async function created(grant: Promise<unknown>): Promise<boolean> {
  try {
    await grant
    return true
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) return false
    throw err
  }
}

async function main(): Promise<void> {
  const daytonaKey = process.env.DAYTONA_API_KEY
  if (!daytonaKey) {
    console.error('Error: set DAYTONA_API_KEY in .env (see .env.example)')
    process.exit(1)
  }
  const client = omnaraClient()
  const model = await agentModel()
  await checkDaytonaKey(daytonaKey)
  const orgID = await resolveOrg(client)
  const modelID = await configuredModelID(client, orgID, model)

  const existingProject = await findProject(client, orgID)
  const project =
    existingProject ?? (await sdk.createProject({ client, path: { orgID }, body: { name: PROJECT_NAME } })).data
  console.log(`Project ${PROJECT_NAME}: ${existingProject ? 'already exists' : 'created'}`)

  const material = { kind: 'generic' as const, value: daytonaKey }
  const existingSecret = await findSecret(client, orgID)
  const secret =
    existingSecret ??
    (await sdk.createSecret({ client, path: { orgID }, body: { owner: { kind: 'org' }, name: SECRET_NAME, material } }))
      .data
  console.log(`Secret ${SECRET_NAME}: ${existingSecret ? 'already exists' : 'created'}`)

  const existingPool = await findPool(client, orgID)
  const machinePool = existingPool ?? (await createPool(client, orgID, secret.id))
  console.log(`Machine pool ${POOL_NAME}: ${existingPool ? 'already exists' : 'created'}`)

  const path = { orgID, projectID: project.id }
  const poolGranted = await created(
    sdk.createProjectMachinePoolGrant({ client, path, body: { machine_pool_id: machinePool.id } }),
  )
  console.log(`Pool grant: ${poolGranted ? 'created' : 'already exists'}`)
  const modelGranted = await created(
    sdk.createProjectModelGrant({ client, path, body: { configured_model_id: modelID } }),
  )
  console.log(`Model grant for ${model.name}: ${modelGranted ? 'created' : 'already exists'}`)

  if (existingSecret || existingPool) {
    console.log(
      '\nSetup left existing resources as they are. To change the Daytona key or pool settings, ' +
        'run `npm run cleanup` first.',
    )
  }
  console.log('\nSetup is done. Run `npm run start` to launch the agent.')
}

main().catch((error) => {
  console.error('An error occurred:', error instanceof Error ? error.message : error)
  process.exit(1)
})
