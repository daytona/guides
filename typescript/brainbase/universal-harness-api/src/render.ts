/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { ThreadEvent } from './client.js'

const BOLD = '\x1b[1m'
const DIM = '\x1b[2m'
const RESET = '\x1b[0m'

// Pull display text out of an event/message payload, which may be a string,
// a { content } string, or a { content: [{ type: 'text', content }] } array.
function extractText(data: any): string {
  if (!data) return ''
  if (typeof data === 'string') return data
  const content = data.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content.map((part: any) => (typeof part === 'string' ? part : part?.content ?? part?.text ?? '')).join('')
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
        const text = extractText(event.data)
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
        const text = extractText(event.data)
        if (this.streaming) {
          // We already streamed this message chunk by chunk; just close it off.
          this.endStream()
        } else if (text && text !== this.lastAssistant) {
          console.log(`\n${BOLD}Agent:${RESET} ${text}`)
          this.lastAssistant = text
        }
        break
      }
      case 'tool_call.start': {
        this.endStream()
        const name = event.data?.name ?? event.data?.tool ?? event.data?.tool_name ?? 'tool'
        console.log(`${DIM}  -> ${name}${RESET}`)
        break
      }
      case 'mcp.status': {
        this.endStream()
        const servers: any[] = Array.isArray(event.data?.servers) ? event.data.servers : []
        if (servers.length) {
          const summary = servers.map((s) => `${s.name} (${s.status})`).join(', ')
          console.log(`${DIM}  · mcp: ${summary}${RESET}`)
        }
        break
      }
      case 'idle': {
        this.endStream()
        const status = event.data?.status ?? 'idle'
        const summary = event.data?.summary
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
