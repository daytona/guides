/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import * as dotenv from 'dotenv'
import { ApiError, BrainbaseClient } from './client.js'
import { Renderer } from './render.js'
import { agent, initialInput, followUpInput, BRAINBASE_BASE_URL } from './config.js'

dotenv.config()

const RULE = '-'.repeat(60)

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// Append a message and start the next turn. A turn's run lease lingers briefly
// after its `idle` event, so the API can answer 409 ("task is busy") for a
// moment; retry until the lease is released.
async function sendAndRun(client: BrainbaseClient, threadId: string, content: string): Promise<void> {
  const deadline = Date.now() + 30_000
  for (;;) {
    try {
      await client.postMessages(threadId, [{ content }], true)
      return
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && Date.now() < deadline) {
        await sleep(1_500)
        continue
      }
      throw err
    }
  }
}

// Abort the stream if no events arrive for this long (a safety net so the
// demo never hangs forever waiting on a turn that will not settle).
const IDLE_TIMEOUT_MS = 5 * 60 * 1000

// How many prior events to replay when the stream opens. The first turn starts
// the moment the thread is created, so backfill catches anything emitted before
// the stream connects; the connection then continues live across turns.
const BACKFILL = 1000

// Collapse a message body to a single trimmed line for the transcript summary.
function oneLine(content: string | null, max = 120): string {
  const text = (content ?? '').replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

async function main(): Promise<void> {
  const apiKey = process.env.BRAINBASE_API_KEY
  if (!apiKey) {
    console.error('Error: BRAINBASE_API_KEY environment variable is not set')
    process.exit(1)
  }

  const client = new BrainbaseClient(apiKey, BRAINBASE_BASE_URL)
  const harness = agent.harness ?? 'claude_code'
  const provider = agent.machine_kind ?? 'daytona'

  // One call describes the agent, boots a sandbox on the chosen provider, and
  // starts the first turn from `input`.
  console.log(`Creating a "${harness}" agent on ${provider}...`)
  const { thread_id, agent_id } = await client.createThread({ agent, input: initialInput })
  console.log(`Thread ${thread_id} (agent ${agent_id})`)
  console.log(`\n${RULE}\nUser: ${initialInput}`)

  // Open the thread's event stream. `backfill` replays events already emitted
  // since creation, so nothing from the first turn is missed; the same
  // connection then stays open and carries every following turn.
  const controller = new AbortController()
  const stream = await client.openEventStream(thread_id, { backfill: BACKFILL, signal: controller.signal })

  // Track why we abort, so the abort is reported correctly (or not) below.
  let abortReason: 'timeout' | 'interrupt' | null = null

  // Ctrl+C asks Brainbase to stop the running turn (server-side) and tears the
  // local stream down cleanly.
  const onSigint = () => {
    console.log('\nInterrupting...')
    abortReason = 'interrupt'
    controller.abort()
    client
      .interrupt(thread_id)
      .catch(() => {})
      .finally(() => process.exit(0))
  }
  process.once('SIGINT', onSigint)

  const renderer = new Renderer()
  const followUps = [followUpInput]

  // (Re)arm the inactivity watchdog on every event.
  let timer: ReturnType<typeof setTimeout> | undefined
  const arm = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      abortReason = 'timeout'
      controller.abort()
    }, IDLE_TIMEOUT_MS)
  }
  arm()

  try {
    for await (const event of stream.events()) {
      arm()
      renderer.handle(event)

      // `idle` marks the end of a turn. Send the next follow-up on the same
      // thread — same sandbox, full context — or finish if there are none left.
      if (event.type === 'idle') {
        const next = followUps.shift()
        if (!next) break
        console.log(`\n${RULE}\nUser: ${next}`)
        await sendAndRun(client, thread_id, next)
      }
    }
  } catch (err) {
    if (!controller.signal.aborted) throw err
    // Ctrl+C is handled by the SIGINT handler (which exits the process); only
    // the inactivity watchdog needs to report here.
    if (abortReason === 'interrupt') return
    console.error('\nStream stopped (inactivity timeout).')
  } finally {
    if (timer) clearTimeout(timer)
    await stream.close()
    controller.abort()
    process.removeListener('SIGINT', onSigint)
  }

  // Show the Daytona sandbox that ran the agent, plus the final transcript.
  const thread = await client.getThread(thread_id)
  console.log(`\n${RULE}`)
  const machine = thread.sandbox_id ?? thread.machine_id
  if (machine) console.log(`Ran on ${provider} sandbox: ${machine}`)
  console.log(`Final status: ${thread.status}`)

  const { items } = await client.listMessages(thread_id)
  console.log(`\nTranscript (${items.length} messages):`)
  for (const message of items) {
    const body = oneLine(message.content)
    if (body) console.log(`  ${message.role}: ${body}`)
  }
}

main().catch((error) => {
  console.error('An error occurred:', error)
  process.exit(1)
})
