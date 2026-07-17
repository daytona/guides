/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { ThreadEvent } from './client.js'

// Enable ANSI styling only when writing to a real terminal, so redirected or
// piped output (files, CI logs) stays clean plain text.
const useColor = process.stdout.isTTY === true
const BOLD = useColor ? '\x1b[1m' : ''
const DIM = useColor ? '\x1b[2m' : ''
const RESET = useColor ? '\x1b[0m' : ''

// Strip terminal escape/control sequences from untrusted event text so agent or
// tool output can't spoof the console. Tabs and newlines are kept (agent
// messages are often multi-line); carriage returns are dropped so they can't
// overwrite the current line.
function sanitize(text: string): string {
  return text
    .replace(/\u001B\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, '')
}

// Pull display text out of an event/message payload, which may be a string,
// a { content } string, or a { content: [{ type: 'text', content }] } array.
// Only text blocks are included, so non-text blocks (tool calls, images) never
// land under the "Agent:" label.
function extractText(data: any): string {
  if (!data) return ''
  if (typeof data === 'string') return data
  const content = data.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .filter((part: any) => typeof part === 'string' || part?.type === 'text' || part?.type == null)
      .map((part: any) => (typeof part === 'string' ? part : part?.content ?? part?.text ?? ''))
      .join('')
  }
  return ''
}

// Renders a thread's event stream to the console: assistant messages, tool
// calls, MCP status, and turn outcomes as they arrive. Harnesses may send the
// reply as streamed `assistant.message.chunk`s, as one complete
// `assistant.message`, or both; either way the text is sanitized once (so an
// escape sequence can't be split across chunks) and de-duplicated within a turn.
export class Renderer {
  private lastAssistant = ''
  private pending = ''

  handle(event: ThreadEvent): void {
    switch (event.type) {
      // Streamed assistant text: accumulate raw and print once the message is
      // complete, so sanitization sees whole escape sequences, not fragments.
      case 'assistant.message.chunk': {
        this.pending += extractText(event.data)
        break
      }
      // A complete assistant message supersedes any chunks accumulated for it.
      case 'assistant.message': {
        this.pending = ''
        this.printAgent(extractText(event.data))
        break
      }
      case 'tool_call.start': {
        this.flushPending()
        const name = sanitize(String(event.data?.name ?? event.data?.tool ?? event.data?.tool_name ?? 'tool'))
        console.log(`${DIM}  -> ${name}${RESET}`)
        break
      }
      case 'mcp.status': {
        this.flushPending()
        const servers: any[] = Array.isArray(event.data?.servers) ? event.data.servers : []
        if (servers.length) {
          const summary = servers.map((s) => sanitize(`${s.name} (${s.status})`)).join(', ')
          console.log(`${DIM}  · mcp: ${summary}${RESET}`)
        }
        break
      }
      case 'idle': {
        this.flushPending()
        const status = sanitize(String(event.data?.status ?? 'idle'))
        const summary = event.data?.summary ? sanitize(String(event.data.summary)) : ''
        console.log(`${DIM}● turn ${status}${summary ? `: ${summary}` : ''}${RESET}`)
        // Start each turn's de-dup fresh.
        this.lastAssistant = ''
        break
      }
      default:
        // Other event types (keepalives, internal bookkeeping) are ignored.
        break
    }
  }

  // Flush assistant text that arrived as chunks without a terminating
  // `assistant.message` (some harnesses only stream chunks).
  private flushPending(): void {
    const raw = this.pending
    this.pending = ''
    this.printAgent(raw)
  }

  // Print an assistant message, sanitized once and de-duplicated within a turn
  // (some harnesses emit the final message more than once).
  private printAgent(raw: string): void {
    const text = sanitize(raw)
    if (text && text !== this.lastAssistant) {
      console.log(`\n${BOLD}Agent:${RESET} ${text}`)
      this.lastAssistant = text
    }
  }
}
