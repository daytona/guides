/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

// Load .env before importing ./config, which reads process.env at module load.
import 'dotenv/config'
import { ApiError, BrainbaseClient, EventStream } from './client.js'
import { Renderer } from './render.js'
import { agent, initialInput, followUpInput, BRAINBASE_BASE_URL } from './config.js'

const RULE = '-'.repeat(60)

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// Append a message and start the next turn. A turn's run lease lingers briefly
// after its `idle` event, so the API can answer 409 ("task is busy") for a
// moment; retry (up to ~30s) until the lease is released.
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

// Ask Brainbase to stop the current turn, but never block longer than `ms` so
// Ctrl+C and the timeout path stay responsive if the network stalls.
async function bestEffortInterrupt(client: BrainbaseClient, threadId: string, ms = 3_000): Promise<void> {
  await Promise.race([client.interrupt(threadId).catch(() => {}), sleep(ms)])
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

  // Track why we abort, so the abort is reported correctly (or not) below.
  const controller = new AbortController()
  let abortReason: 'timeout' | 'interrupt' | null = null

  // Register Ctrl+C handling before opening the stream: the turn is already
  // running server-side, so an interrupt while connecting must still stop it.
  const onSigint = () => {
    console.log('\nInterrupting...')
    abortReason = 'interrupt'
    controller.abort()
    void bestEffortInterrupt(client, thread_id).finally(() => process.exit(0))
  }
  process.once('SIGINT', onSigint)

  // Open the thread's event stream. `backfill` replays up to the most recent
  // BACKFILL events emitted since creation, so the start of the first turn is
  // captured; the same connection then stays open and carries every turn.
  let stream: EventStream
  try {
    stream = await client.openEventStream(thread_id, { backfill: BACKFILL, signal: controller.signal })
  } catch (err) {
    // Ctrl+C during connect aborts this request; let the SIGINT handler's
    // best-effort interrupt and exit take over instead of crashing with exit 1.
    if (controller.signal.aborted) return
    throw err
  }

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

  let completed = false
  try {
    for await (const event of stream.events()) {
      arm()
      renderer.handle(event)

      // `idle` marks the end of a turn. Send the next follow-up on the same
      // thread — same sandbox, full context — or finish if there are none left.
      if (event.type === 'idle') {
        const next = followUps.shift()
        if (!next) {
          completed = true
          break
        }
        console.log(`\n${RULE}\nUser: ${next}`)
        await sendAndRun(client, thread_id, next)
      }
    }
  } catch (err) {
    if (!controller.signal.aborted) throw err
    // Ctrl+C is handled by the SIGINT handler (which exits the process); only
    // the inactivity watchdog needs to report here.
    if (abortReason === 'interrupt') return
    console.error('\nStream stopped (inactivity timeout); interrupting the turn.')
    await bestEffortInterrupt(client, thread_id)
  } finally {
    if (timer) clearTimeout(timer)
    await stream.close()
    controller.abort()
    process.removeListener('SIGINT', onSigint)
  }

  // A clean run ends when the final turn reports idle. If the stream closed
  // first (not via our timeout/interrupt, which set abortReason), warn that the
  // transcript below may be incomplete.
  if (!completed && abortReason === null) {
    console.error('\nStream ended before the final turn settled; results may be incomplete.')
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
