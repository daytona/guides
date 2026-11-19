/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Sandbox, PtyHandle } from '@daytona/sdk/v0'
import { GooseEvent, GooseMessageEvent, GooseErrorEvent, GooseExitEvent, GooseToolResponseBlock } from './types.js'

const WORK_DIR = '/home/daytona'

const DEBUG = false
function debug(...args: unknown[]) {
  if (DEBUG) console.error('[debug]', ...args)
}

export function formatPreview(input: string, maxLength = 80): string {
  const normalized = input.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized
}

// The argument worth showing next to a tool name, e.g. "shell: npm test" or "write: app.py".
// Goose's built-in tools take `command` (shell), `path` (write, edit, tree, analyze) or
// `source` (read_image, load); the other keys cover extension tools.
const TOOL_DETAIL_KEYS = ['command', 'path', 'source', 'uri', 'extension_name', 'query', 'instructions']

function describeToolCall(name: string, args: Record<string, unknown> = {}): string {
  const detail = TOOL_DETAIL_KEYS.map((key) => args[key]).find((value) => typeof value === 'string' && value.trim())
  return typeof detail === 'string' ? `${name}: ${formatPreview(detail)}` : name
}

// A tool fails either before it runs (status "error") or by flagging its result with isError.
function toolError(block: GooseToolResponseBlock): string | null {
  const result = block.toolResult
  if (result.status === 'error') return result.error
  if (!result.value.isError) return null
  return result.value.content
    .filter((part) => part.type === 'text' && part.text)
    .map((part) => part.text)
    .join('\n')
}

export class GooseSession {
  private ptyHandle: PtyHandle | null = null
  private buffer = ''
  // Reused across handleData calls so partial multi-byte UTF-8 sequences split
  // across PTY chunks are preserved instead of producing corrupt characters.
  private decoder = new TextDecoder('utf-8')
  private onResponseComplete?: () => void
  // False until a turn has run to completion; afterwards each turn adds --resume so
  // Goose continues its most recent session (there is no explicit session/thread ID
  // to track - unlike Amp or Gemini, Goose resume is just "continue the last one").
  private resumable = false
  // Whether the current turn has reported its outcome ("complete" or "error").
  private turnEnded = false
  // Sent via --system on the first turn only; Goose carries it forward as part of
  // the session it resumes from then on, so it is not resent on later turns.
  private systemPrompt: string | null = null
  // Whether the terminal cursor sits at the start of a line, so status lines can start on
  // a fresh line without leaving blank lines between them.
  private atLineStart = true

  constructor(private sandbox: Sandbox) {}

  private write(text: string, stream: NodeJS.WriteStream = process.stdout): void {
    if (!text) return
    stream.write(text)
    this.atLineStart = text.endsWith('\n')
  }

  private writeLine(line: string, stream: NodeJS.WriteStream = process.stdout): void {
    this.write(`${this.atLineStart ? '' : '\n'}${line}\n`, stream)
  }

  // Quote a string so it is passed to a shell command literally.
  private shellQuote(s: string): string {
    return `'${s.replace(/'/g, "'\\''")}'`
  }

  private handleEvent(event: GooseEvent): void {
    switch (event.type) {
      case 'message': {
        // Assistant messages carry streamed reply text and tool requests; tool
        // responses come back in user messages.
        const msg = (event as GooseMessageEvent).message
        for (const block of msg.content) {
          if (block.type === 'text' && msg.role === 'assistant') {
            this.write(block.text)
          } else if (block.type === 'toolRequest' && block.toolCall.status === 'success') {
            this.writeLine(`[tool] ${describeToolCall(block.toolCall.value.name, block.toolCall.value.arguments)}`)
          } else if (block.type === 'toolResponse') {
            const error = toolError(block)
            if (error) this.writeLine(`[tool error] ${error}`)
          }
        }
        return
      }
      case 'complete': {
        // The turn ran to completion, so later turns can --resume its session.
        this.resumable = true
        this.turnEnded = true
        if (!this.atLineStart) this.write('\n')
        return
      }
      case 'error': {
        // Provider failures (bad API key, quota, etc.) end the turn with this event
        // instead of "complete".
        this.turnEnded = true
        this.writeLine(`Failed: ${(event as GooseErrorEvent).error}`, process.stderr)
        return
      }
      case 'goose_exit': {
        // `goose run` has exited. If it never reported an outcome (for example a setup
        // error it prints as plain text), the turn still ends here instead of hanging.
        if (!this.turnEnded) {
          const code = (event as GooseExitEvent).code
          this.writeLine(`Failed: goose exited with code ${code} (set DEBUG = true in src/session.ts to see its output)`, process.stderr)
        }
        this.onResponseComplete?.()
        return
      }
    }
  }

  // Buffer raw PTY bytes and dispatch each complete newline-delimited JSON event.
  private handleData(data: Uint8Array): void {
    this.buffer += this.decoder.decode(data, { stream: true })
    const lines = this.buffer.split('\n')
    this.buffer = lines.pop() || ''
    for (const line of lines.map((l) => l.trim()).filter(Boolean)) {
      let event: GooseEvent
      try {
        event = JSON.parse(line) as GooseEvent
      } catch {
        debug('non-JSON line:', line)
        continue
      }
      try {
        this.handleEvent(event)
      } catch (e) {
        // Report handler bugs instead of throwing: an exception escaping this PTY
        // callback would crash the process before it deletes the sandbox.
        console.error('Error handling Goose event:', e)
      }
    }
  }

  async initialize(options?: { systemPrompt?: string }): Promise<void> {
    this.ptyHandle = await this.sandbox.process.createPty({
      id: `goose-pty-${Date.now()}`,
      cols: 120,
      rows: 30,
      onData: (data: Uint8Array) => this.handleData(data),
    })
    await this.ptyHandle.waitForConnection()
    // Goose installs to ~/.local/bin, which a fresh shell may not have on PATH.
    // Exported once here since this PTY (and its shell) is reused for every turn.
    await this.ptyHandle.sendInput('export PATH="$HOME/.local/bin:$PATH"\n')

    if (options?.systemPrompt?.trim()) {
      this.systemPrompt = options.systemPrompt.trim()
    }
  }

  // Run a single headless turn and resolve once `goose run` exits.
  async processPrompt(prompt: string): Promise<void> {
    const flags = ['run', '--output-format', 'stream-json', '--text', this.shellQuote(prompt)]
    if (this.resumable) {
      // Goose resumes the most recent session; there is no ID to pass explicitly.
      flags.push('--resume')
    } else if (this.systemPrompt) {
      flags.push('--system', this.shellQuote(this.systemPrompt))
    }
    const command = ['goose', ...flags].join(' ')
    debug('running:', command)

    // Register the completion handler before sending, so a fast turn can't finish
    // before anything is listening for it.
    this.turnEnded = false
    const turnDone = new Promise<void>((resolve) => {
      this.onResponseComplete = resolve
    })
    // Pressing Enter at the prompt left the cursor on a new line. Goose takes a few
    // seconds to start and reach the model, so show that the turn is underway.
    this.atLineStart = true
    this.writeLine('Thinking...')
    // The printf runs however goose exits and reports its exit code as a goose_exit line.
    await this.ptyHandle!.sendInput(`cd ${WORK_DIR} && ${command}; printf '{"type":"goose_exit","code":%d}\\n' $?\n`)
    await turnDone
  }

  async cleanup(): Promise<void> {
    try {
      if (this.ptyHandle) await this.ptyHandle.kill()
    } catch (e) {
      debug('error killing PTY session:', e)
    }
  }
}
