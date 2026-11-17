/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Sandbox } from '@daytona/sdk/v0'

const WORK_DIR = '/home/daytona'
const KIRO = '"$HOME/.local/bin/kiro-cli"'
// One-shot marker that lets us hide the single launch line (the sandbox's interactive
// shell echoes and decorates input via its line editor, which `stty -echo` cannot
// disable). The regex tolerates the PTY's NL->CRNL conversion; the echoed launch line
// carries the marker inside quotes, not bounded by newlines, so it never false-matches.
const READY = '__DAYTONA_KIRO_READY__'
const READY_RE = new RegExp(`(^|[\\r\\n])${READY}[\\r\\n]`)

export class KiroSession {
  private decoder = new TextDecoder('utf-8')
  private passthrough = false
  private launchBuffer = ''
  // False until the first turn creates a conversation; afterwards each turn adds
  // --resume so Kiro continues the most recent conversation from WORK_DIR (the
  // prior turn), carrying context across turns.
  private resumable = false

  constructor(private sandbox: Sandbox) {}

  // Quote a string so it is passed to the shell literally (prevents shell injection).
  private shellQuote(s: string): string {
    return `'${s.replace(/'/g, "'\\''")}'`
  }

  // Until the readiness marker is seen, swallow the shell's launch noise (prompt +
  // input echo); after it, forward every byte raw so Kiro's TUI renders exactly as
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
  // is load-bearing: it hands the PTY directly to Kiro, so the session ends when Kiro
  // exits and there is no shell prompt or line-editor echo wrapping its output.
  private async attach(command: string, interactive: boolean): Promise<number | undefined> {
    this.decoder = new TextDecoder('utf-8')
    this.passthrough = false
    this.launchBuffer = ''

    const pty = await this.sandbox.process.createPty({
      id: `kiro-pty-${Date.now()}`,
      cols: process.stdout.columns || 120,
      rows: process.stdout.rows || 30,
      onData: (data: Uint8Array) => this.forward(data),
    })
    await pty.waitForConnection()
    await pty.sendInput(`cd ${WORK_DIR}; printf '\\n%s\\n' '${READY}'; exec ${command}\n`)

    const stdin = process.stdin
    const onStdin = (chunk: Buffer) => void pty.sendInput(chunk)
    if (interactive) {
      // Discard input buffered before this step (e.g. trailing bytes from a paste in
      // the prior step) so it is not misread as input to this command.
      while (stdin.read() !== null) {
        /* drain */
      }
      if (stdin.isTTY) stdin.setRawMode(true)
      stdin.resume()
      stdin.on('data', onStdin)
    }
    try {
      const result = await pty.wait()
      return result.exitCode
    } finally {
      if (interactive) {
        stdin.removeListener('data', onStdin)
        if (stdin.isTTY) stdin.setRawMode(false)
        stdin.pause()
      }
      try {
        await pty.disconnect()
      } catch {
        // Ignore disconnect errors on an already-closed PTY.
      }
    }
  }

  async initialize(): Promise<void> {
    // PTYs are created per invocation, so there is nothing to set up ahead of time.
  }

  // Drive Kiro's device-flow login: the user picks a provider (Builder ID, Google, or
  // GitHub - all free), opens the printed URL, and approves the sign-in in their own
  // browser while the sandbox-side CLI polls AWS until it completes. Kiro's native
  // login TUI runs directly in the PTY; `kiro-cli whoami` is the source of truth.
  async login(): Promise<void> {
    await this.attach(`${KIRO} login --use-device-flow`, true)
    const status = await this.sandbox.process.executeCommand(`${KIRO} whoami`)
    if (status.exitCode !== 0) {
      throw new Error(
        'Kiro login did not complete. Re-run and approve the sign-in when prompted.\n' +
          `kiro-cli whoami (exit ${status.exitCode}):\n${status.result}`,
      )
    }
  }

  // Run a single headless task. `--no-interactive` prints the response and exits,
  // `--trust-all-tools` auto-approves tools so the run never blocks on a prompt, and
  // `--resume` (every turn after the first) continues the most recent conversation
  // from WORK_DIR so context carries across turns.
  async processPrompt(prompt: string): Promise<void> {
    const resume = this.resumable ? '--resume ' : ''
    const exitCode = await this.attach(
      `${KIRO} chat --no-interactive --trust-all-tools ${resume}${this.shellQuote(prompt)}`,
      false,
    )
    // Only mark the conversation resumable once a turn has actually succeeded. A failed first
    // turn creates no conversation, so a later --resume would have nothing to continue; once
    // any turn succeeds this stays true, so a later failure does not drop the resume context.
    if (exitCode === 0) this.resumable = true
    process.stdout.write('\n')
  }

  async cleanup(): Promise<void> {
    // Each PTY closes at the end of its invocation, so there is no session to tear
    // down. The one thing worth guarding is the local terminal: if the process is
    // interrupted while an interactive phase still has it in raw mode, restore cooked
    // mode so the shell is not left garbled after exit.
    if (process.stdin.isTTY) process.stdin.setRawMode(false)
  }
}
