/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

// A minimal client for the Brainbase Universal Harness API.
// One call describes an agent — any harness, any config — and runs it in an
// isolated sandbox. Docs: https://docs.brainbaselabs.com/api

// Thrown for any non-2xx response, carrying the HTTP status so callers can
// react to specific cases — e.g. retrying a 409 while a just-finished turn
// releases its run lock.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly statusText: string,
    readonly body: string,
  ) {
    super(`${status} ${statusText}${body ? `: ${body}` : ''}`)
    this.name = 'ApiError'
  }
}

// Harnesses accepted by the API today (the public name for `runtime_kind`).
export type Harness =
  | 'claude_code'
  | 'codex'
  | 'cursor'
  | 'factory'
  | 'kafka_cloud'
  | 'opencode'
  | 'qoder'
  | 'qwen'

export interface McpServer {
  name: string
  url?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  headers?: Record<string, string>
  is_enabled?: boolean
}

// The whole agent, inline: harness, instructions, model, tools, and the
// sandbox provider it runs on. Brainbase hashes this spec and reuses the match,
// so sending the same spec twice returns the same agent with a new thread.
export interface AgentSpec {
  harness?: Harness
  instructions?: string
  model?: string
  // Sandbox provider. Daytona is the API default; this guide runs on Daytona.
  machine_kind?: 'daytona'
  mcp_servers?: McpServer[]
  skills?: { source: string }[]
  secrets?: Record<string, string>
  entrypoint?: string
  title?: string
}

export interface CreateThreadRequest {
  agent?: AgentSpec
  agent_id?: string
  input?: string
  messages?: { role?: string; content: string }[]
  title?: string
  metadata?: Record<string, unknown>
}

export interface CreateThreadResponse {
  thread_id: string
  agent_id: string
  status: string
}

// A thread's status settles to `success` / `fail` for a finished turn,
// `need_more_info` when the agent is waiting on you, or `idle`.
export interface Thread {
  id: string
  agent_id: string
  title: string | null
  status: string
  status_info?: unknown
  sandbox_id?: string | null
  machine_id?: string | null
  metadata?: Record<string, unknown>
  created_at: string
}

export interface Message {
  role: string
  content: string | null
  metadata?: Record<string, unknown>
}

// A typed server-sent event from a thread's stream. The ones you'll see most
// are `assistant.message.chunk` (streaming text), `tool_call.start`, and
// `idle` (the turn's outcome and a summary).
export interface ThreadEvent {
  type: string
  thread_id?: string
  data?: any
}

export class BrainbaseClient {
  private readonly apiKey: string
  private readonly baseUrl: string

  constructor(apiKey: string, baseUrl = 'https://api.brainbaselabs.com') {
    this.apiKey = apiKey
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return { Authorization: `Bearer ${this.apiKey}`, ...extra }
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: this.headers(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new ApiError(res.status, res.statusText, detail)
    }
    // Some endpoints (e.g. interrupt) can answer 204 or an empty/whitespace
    // body; don't try to JSON-parse nothing.
    if (res.status === 204) return undefined as T
    const text = (await res.text()).trim()
    return (text ? JSON.parse(text) : undefined) as T
  }

  // Describe the agent inline and (optionally) pass its first input. Brainbase
  // creates the agent, boots a sandbox, and — if `input`/`messages` are set —
  // starts the first turn. One request, nothing to set up beforehand.
  createThread(body: CreateThreadRequest): Promise<CreateThreadResponse> {
    return this.request('POST', '/v2/threads', body)
  }

  // Poll a thread's status (and see the `sandbox_id` / `machine_id` backing it).
  getThread(threadId: string): Promise<Thread> {
    return this.request('GET', `/v2/threads/${threadId}`)
  }

  // Fetch the full transcript. Messages arrive in an `items` array.
  listMessages(threadId: string): Promise<{ items: Message[] }> {
    return this.request('GET', `/v2/threads/${threadId}/messages`)
  }

  // Append messages to a thread. With `run: true` the agent picks the thread
  // back up in the same sandbox, with full context.
  postMessages(
    threadId: string,
    messages: { role?: string; content: string }[],
    run = true,
  ): Promise<{ run_started: boolean }> {
    return this.request('POST', `/v2/threads/${threadId}/messages`, { messages, run })
  }

  // Stop the current turn.
  interrupt(threadId: string): Promise<unknown> {
    return this.request('POST', `/v2/threads/${threadId}/interrupt`)
  }

  // Open the thread's live event stream. The returned handle is connected and
  // listening as soon as this resolves, so you can start a turn afterwards
  // without racing the first events. The connection stays open across turns.
  async openEventStream(
    threadId: string,
    opts: { backfill?: number; signal?: AbortSignal } = {},
  ): Promise<EventStream> {
    const url = new URL(`${this.baseUrl}/v2/threads/${threadId}/events/stream`)
    if (opts.backfill != null) url.searchParams.set('backfill', String(opts.backfill))
    const res = await fetch(url, {
      headers: this.headers({ Accept: 'text/event-stream' }),
      signal: opts.signal,
    })
    if (!res.ok || !res.body) {
      const detail = res.ok ? 'no response body' : await res.text().catch(() => '')
      throw new ApiError(res.status, res.statusText, detail)
    }
    return new EventStream(res.body)
  }
}

// Parses a server-sent event byte stream into typed `ThreadEvent`s.
export class EventStream {
  private readonly reader: ReadableStreamDefaultReader<Uint8Array>
  private readonly decoder = new TextDecoder()
  private buffer = ''

  constructor(body: ReadableStream<Uint8Array>) {
    this.reader = body.getReader()
  }

  async *events(): AsyncGenerator<ThreadEvent> {
    try {
      while (true) {
        const { done, value } = await this.reader.read()
        if (done) break
        // Strip CRs so frame separation works for both "\n\n" and "\r\n\r\n".
        this.buffer += this.decoder.decode(value, { stream: true }).replace(/\r/g, '')
        let sep: number
        while ((sep = this.buffer.indexOf('\n\n')) !== -1) {
          const frame = this.buffer.slice(0, sep)
          this.buffer = this.buffer.slice(sep + 2)
          const event = parseFrame(frame)
          if (event) yield event
        }
      }
    } finally {
      this.reader.releaseLock()
    }
  }

  async close(): Promise<void> {
    await this.reader.cancel().catch(() => {})
  }
}

// Parse one SSE frame ("event:" and "data:" lines) into a ThreadEvent.
function parseFrame(frame: string): ThreadEvent | null {
  let eventType = ''
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line === '' || line.startsWith(':')) continue // blank or keepalive comment
    if (line.startsWith('event:')) eventType = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  if (dataLines.length === 0 && eventType === '') return null
  const raw = dataLines.join('\n')
  try {
    const parsed = raw ? JSON.parse(raw) : {}
    return { type: parsed.type ?? eventType, thread_id: parsed.thread_id, data: parsed.data ?? parsed }
  } catch {
    return { type: eventType, data: raw }
  }
}
