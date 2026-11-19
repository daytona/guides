/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Sandbox, PtyHandle } from '@daytona/sdk'
import { GooseEvent, GooseMessageEvent, GooseErrorEvent, GooseToolResponseBlock } from './types.js'

const WORK_DIR = '/home/daytona'

const DEBUG = false
function debug(...args: unknown[]) {
  if (DEBUG) console.error('[debug]', ...args)
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
  // Sent via --system on the first turn only; Goose carries it forward as part of
  // the session it resumes from then on, so it is not resent on later turns.
  private systemPrompt: string | null = null

  constructor(private sandbox: Sandbox) {}

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
            process.stdout.write(block.text)
          } else if (block.type === 'toolRequest' && block.toolCall.status === 'success') {
            process.stdout.write(`\n[tool] ${block.toolCall.value.name}\n`)
          } else if (block.type === 'toolResponse') {
            const error = toolError(block)
            if (error) process.stdout.write(`\n[tool error] ${error}\n`)
          }
        }
        return
      }
      case 'complete': {
        // The turn ran to completion, so later turns can --resume its session.
        this.resumable = true
        process.stdout.write('\n')
        this.onResponseComplete?.()
        return
      }
      case 'error': {
        // Provider failures (bad API key, quota, etc.) end the turn with this event
        // instead of "complete".
        process.stderr.write(`\nFailed: ${(event as GooseErrorEvent).error}\n`)
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
      try {
        this.handleEvent(JSON.parse(line) as GooseEvent)
      } catch {
        debug('non-JSON line:', line)
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

  // Run a single headless turn and resolve once Goose emits its "complete" or "error" event.
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
    const turnDone = new Promise<void>((resolve) => {
      this.onResponseComplete = resolve
    })
    await this.ptyHandle!.sendInput(`cd ${WORK_DIR} && ${command}\n`)
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
