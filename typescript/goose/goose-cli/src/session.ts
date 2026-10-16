/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Sandbox, PtyHandle } from '@daytona/sdk'
import { GooseEvent, GooseMessageEvent, GooseErrorEvent } from './types.js'

const WORK_DIR = '/home/daytona'

const DEBUG = false
function debug(...args: unknown[]) {
  if (DEBUG) console.error('[debug]', ...args)
}

// Goose doesn't emit a `{type:"error"}` event for provider/model failures (auth,
// quota, etc). Instead it wraps them in an assistant message whose text is
// "Ran into this error: <detail>. Please retry if you think this is a transient or
// recoverable error." and then emits a plain `complete`. This regex captures
// <detail> (dropping the retry boilerplate) so the `complete` handler can surface a
// real error instead of the turn looking like a clean, empty success.
const GOOSE_ERROR_TEXT =
  /^\s*Ran into this error:\s*([\s\S]+?)\.?\s*(?:Please retry if you think this is a transient or recoverable error\.?)?\s*$/i

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
  // Detail from a wrapped provider error, stashed by handleEvent's "message" case for
  // the "complete" case to report.
  private pendingError: string | null = null
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
        const msg = (event as GooseMessageEvent).message
        if (msg.role !== 'assistant') return

        for (const block of msg.content) {
          if (block.type === 'text') {
            const errMatch = block.text.match(GOOSE_ERROR_TEXT)
            if (errMatch) {
              this.pendingError = errMatch[1].trim()
              continue
            }
            process.stdout.write(block.text)
          } else if (block.type === 'tool_use') {
            process.stdout.write(`\n[tool] ${block.name}\n`)
          } else if (block.type === 'tool_result' && block.is_error) {
            const content = block.content
            const output =
              typeof content === 'string'
                ? content
                : Array.isArray(content)
                  ? content
                      .filter((part) => part.type === 'text' && part.text)
                      .map((part) => part.text)
                      .join('\n')
                  : ''
            process.stdout.write(`\n[tool error] ${output}\n`)
          }
        }
        return
      }
      case 'complete': {
        // A turn ran to completion - even a wrapped provider error still creates a
        // resumable session, so this is the right place to flip the flag.
        this.resumable = true
        if (this.pendingError) {
          process.stderr.write(`\nFailed: ${this.pendingError}\n`)
          this.pendingError = null
        }
        process.stdout.write('\n')
        this.onResponseComplete?.()
        return
      }
      case 'error': {
        const err = (event as GooseErrorEvent).error
        const message = typeof err === 'string' ? err : err.message
        process.stderr.write(`\nFailed: ${message}\n`)
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

  // Run a single headless turn and resolve once Goose emits its "complete" event.
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

    await this.ptyHandle!.sendInput(`cd ${WORK_DIR} && ${command}\n`)
    await new Promise<void>((resolve) => {
      this.onResponseComplete = resolve
    })
  }

  async cleanup(): Promise<void> {
    try {
      if (this.ptyHandle) await this.ptyHandle.kill()
    } catch (e) {
      debug('error killing PTY session:', e)
    }
  }
}
