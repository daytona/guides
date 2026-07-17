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
// tool output can't spoof the console (tab, newline, and carriage return kept).
function sanitize(text: string): string {
  return text
    .replace(/\u001B\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
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

// Renders a thread's event stream to the console: streams assistant text as it
// arrives and labels tool calls, MCP status, and turn outcomes. Some harnesses
// emit the final assistant message more than once per turn, so identical text
// is de-duplicated within a turn.
export class Renderer {
  private streaming = false
  private streamBuffer = ''
  private lastAssistant = ''

  handle(event: ThreadEvent): void {
    switch (event.type) {
      case 'assistant.message.chunk': {
        const text = sanitize(extractText(event.data))
        if (text) {
          if (!this.streaming) {
            process.stdout.write(`\n${BOLD}Agent:${RESET} `)
            this.streaming = true
            this.streamBuffer = ''
          }
          process.stdout.write(text)
          this.streamBuffer += text
        }
        break
      }
      case 'assistant.message': {
        const text = sanitize(extractText(event.data))
        if (this.streaming) {
          // We streamed this message as chunks. If the final text extends what
          // we showed (e.g. we connected mid-stream and missed the start), print
          // the missing remainder so nothing is lost; otherwise just close it.
          if (text && text !== this.streamBuffer) {
            if (text.startsWith(this.streamBuffer)) {
              process.stdout.write(text.slice(this.streamBuffer.length))
            } else {
              process.stdout.write(`\n${BOLD}Agent:${RESET} ${text}`)
            }
            this.streamBuffer = text
          }
          this.endStream()
        } else if (text && text !== this.lastAssistant) {
          console.log(`\n${BOLD}Agent:${RESET} ${text}`)
          this.lastAssistant = text
        }
        break
      }
      case 'tool_call.start': {
        this.endStream()
        const name = sanitize(String(event.data?.name ?? event.data?.tool ?? event.data?.tool_name ?? 'tool'))
        console.log(`${DIM}  -> ${name}${RESET}`)
        break
      }
      case 'mcp.status': {
        this.endStream()
        const servers: any[] = Array.isArray(event.data?.servers) ? event.data.servers : []
        if (servers.length) {
          const summary = servers.map((s) => sanitize(`${s.name} (${s.status})`)).join(', ')
          console.log(`${DIM}  · mcp: ${summary}${RESET}`)
        }
        break
      }
      case 'idle': {
        this.endStream()
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

  // Close off an in-progress streamed line before printing something else.
  private endStream(): void {
    if (this.streaming) {
      process.stdout.write('\n')
      this.streaming = false
      this.lastAssistant = this.streamBuffer
      this.streamBuffer = ''
    }
  }
}
