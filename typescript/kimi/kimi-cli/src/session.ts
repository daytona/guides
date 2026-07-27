/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Sandbox, PtyHandle } from '@daytona/sdk'

const WORK_DIR = '/home/daytona'
const KIMI = '"$HOME/.local/bin/kimi"'
// One-shot marker that lets us hide the single launch line (the sandbox's interactive
// shell echoes and decorates input via its line editor, which `stty -echo` cannot
// disable). The regex tolerates the PTY's NL->CRNL conversion; the echoed launch line
// carries the marker inside quotes, not bounded by newlines, so it never false-matches.
const READY = '__DAYTONA_KIMI_READY__'
const READY_RE = new RegExp(`(^|[\\r\\n])${READY}[\\r\\n]`)

export class KimiSession {
  // Reused across forward calls so partial multi-byte UTF-8 sequences split across
  // PTY chunks are preserved instead of producing corrupt characters.
  private decoder = new TextDecoder('utf-8')
  private passthrough = false
  private launchBuffer = ''
  // The PTY of the turn currently in flight, if any, so an interrupt can kill it.
  private pty: PtyHandle | null = null
  // False until the first turn completes; afterwards each turn adds -C so Kimi
  // continues the most recent session from WORK_DIR (the prior turn), carrying
  // context across turns.
  private resumable = false

  constructor(private sandbox: Sandbox) {}

  // Quote a string so it is passed to the shell literally (prevents shell injection).
  private shellQuote(s: string): string {
    return `'${s.replace(/'/g, "'\\''")}'`
  }

  // Until the readiness marker is seen, swallow the shell's launch noise (prompt +
  // input echo); after it, forward every byte raw so Kimi's output renders exactly as
  // it would on localhost.
  private forward(data: Uint8Array): void {
    const text = this.decoder.decode(data, { stream: true })
    if (this.passthrough) {
      process.stdout.write(text)
      return
    }
    this.launchBuffer += text
    const m = READY_RE.exec(this.launchBuffer)
    if (m) {
      const rest = this.launchBuffer.slice(m.index + m[0].length)
      this.passthrough = true
      this.launchBuffer = ''
      if (rest) process.stdout.write(rest)
    } else if (this.launchBuffer.length > 8192) {
      this.launchBuffer = this.launchBuffer.slice(-READY.length - 2)
    }
  }

  // Runs `command` as the PTY's foreground process and bridges it to the local
  // terminal as a raw 1:1 stream (like `ssh` / `docker exec -it`). The `exec` keyword
  // is load-bearing: it hands the PTY directly to Kimi, so the turn ends when Kimi
  // exits and there is no shell prompt or line-editor echo wrapping its output.
  private async attach(command: string): Promise<number | undefined> {
    this.decoder = new TextDecoder('utf-8')
    this.passthrough = false
    this.launchBuffer = ''

    const pty = await this.sandbox.process.createPty({
      id: `kimi-pty-${Date.now()}`,
      cols: process.stdout.columns || 120,
      rows: process.stdout.rows || 30,
      onData: (data: Uint8Array) => this.forward(data),
    })
    this.pty = pty
    try {
      await pty.waitForConnection()
      await pty.sendInput(`cd ${WORK_DIR}; printf '\\n%s\\n' '${READY}'; exec ${command}\n`)
      const result = await pty.wait()
      return result.exitCode
    } finally {
      this.pty = null
      try {
        await pty.disconnect()
      } catch {
        // Ignore disconnect errors on an already-closed PTY.
      }
    }
  }

  async initialize(): Promise<void> {
    // The API key is injected at sandbox creation and PTYs are created per
    // invocation, so there is nothing to set up ahead of time.
  }

  // Run a single headless task. `-p` processes one prompt and exits, `--yolo`
  // auto-approves tool calls so the run never blocks on a confirmation, and `-C`
  // (every turn after the first) continues the most recent session from WORK_DIR
  // so context carries across turns.
  async processPrompt(prompt: string): Promise<void> {
    const cont = this.resumable ? ' -C' : ''
    const exitCode = await this.attach(`${KIMI} -p ${this.shellQuote(prompt)} --yolo${cont}`)
    // Kimi exits 0 even when the turn itself fails (and failed turns still create a
    // resumable session), so unlike a success check this gate only distinguishes "the
    // CLI ran to completion" from "the launch failed or the turn was killed" - the
    // two cases where a later -C might have no session to continue.
    if (exitCode === 0) this.resumable = true
    process.stdout.write('\n')
  }

  async cleanup(): Promise<void> {
    // Kill the PTY of any turn still in flight so an interrupt mid-turn does not
    // leave a live process behind while the sandbox is deleted; when idle, each
    // turn's PTY has already closed and there is nothing to tear down.
    if (this.pty) {
      try {
        await this.pty.kill()
      } catch {
        // Ignore kill errors on an already-closed PTY.
      }
      this.pty = null
    }
  }
}
