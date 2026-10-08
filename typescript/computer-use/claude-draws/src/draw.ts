/** Let Claude draw on a sketchpad running in a Daytona sandbox desktop. */

import Anthropic from '@anthropic-ai/sdk'
import type { BetaComputerConfirmContext } from '@anthropic-ai/sdk/helpers/beta/toolsets'
import { DaytonaComputer } from '@daytona/claude-toolsets'
import type { Sandbox } from '@daytona/sdk'
import { randomInt } from 'node:crypto'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

const PAINT_HTML = fileURLToPath(new URL('../paint.html', import.meta.url))

// Paths inside the sandbox. The profile doubles as HOME for the scrubbed Chromium environment.
const REMOTE_DIR = '/tmp/claude-draws'
const REMOTE_HTML = `${REMOTE_DIR}/paint.html`
const PROFILE = '/tmp/claude-draws-profile'
const CHROMIUM = 'chromium'
const SESSION_ID = 'claude-draws-chromium'

// The desktop size the sandbox boots with, and the window Chromium opens at.
const WIDTH = 1280
const HEIGHT = 800

// The task names swatches rather than relying on positions because the palette scrolls horizontally.
const TASK = `The screen shows a sketchpad web app called Paint, already open and maximized. Draw in it with the mouse.

How the app works:

- A floating toolbar docks along the top of the window: brush sizes labeled fine, small, medium and bold, a caption box, a live readout, and a Clear button.
- A floating color palette docks along the bottom. It scrolls horizontally and only shows part of itself at a time. Every swatch shows its color name as text under the color chip.
- The canvas fills the whole window behind those two docks.

How to work:

1. Take a screenshot first and find the toolbar and the palette.
2. Choose colors by NAME, never by position. Scroll the palette sideways until the swatch whose label you want is visible, then click that swatch. The readout in the top toolbar then shows the selected color name, so you can confirm the click landed before you draw.
3. Draw only in the middle band of the screen, roughly 120 to 620 pixels from the top. The floating toolbar and palette sit outside that band and will swallow clicks meant for the canvas.
4. Drag the mouse to draw freehand. Hold shift and click to draw a straight line from the last point you drew to the point you click, so shift-clicks chain into a polyline.

What to draw, a simple sunset over water:

- A large round sun in the upper middle of the drawing band, with the swatch labeled "orange".
- A straight horizon line across the drawing band and a few wave strokes under it, with the swatch labeled "teal".
- Two or three small clouds above the horizon, with the swatch labeled "rose".
- Finally click the caption box in the top toolbar and type: sunset by claude

Take a screenshot when you are finished and describe what you drew.`

function confirm(context: BetaComputerConfirmContext): boolean {
  console.log(`[confirm] ${context.member} ${JSON.stringify(context.input)}`)
  return true
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`
}

function positiveInteger(name: string, fallback: number): number {
  const raw = process.env[name]
  if (raw === undefined) return fallback
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`)
  }
  return value
}

async function uploadSketchpad(sandbox: Sandbox): Promise<void> {
  await sandbox.process.executeCommand(
    `mkdir -p -m 700 ${shellQuote(REMOTE_DIR)} ${shellQuote(PROFILE)}`,
  )
  await sandbox.fs.uploadFile(await readFile(PAINT_HTML), REMOTE_HTML)
}

async function readChromiumLog(sandbox: Sandbox): Promise<string> {
  try {
    const result = await sandbox.process.executeCommand(
      `tail -n 40 ${shellQuote(`${PROFILE}/chromium.log`)}`,
      undefined,
      undefined,
      10,
    )
    if (result.exitCode !== 0) {
      return `<could not read the log: tail exited ${result.exitCode}>`
    }
    return result.result.trim() || '<log is empty>'
  } catch (error) {
    return `<could not read the log: ${String(error)}>`
  }
}

async function launchChromium(sandbox: Sandbox): Promise<void> {
  const port = randomInt(20_000, 40_000)
  const isRoot = (await sandbox.process.executeCommand('id -u')).result.trim() === '0'
  const flags = [
    '--remote-debugging-address=127.0.0.1',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${PROFILE}`,
    `--window-size=${WIDTH},${HEIGHT}`,
    '--start-maximized',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-default-apps',
    '--disable-extensions',
    '--disable-sync',
    '--password-store=basic',
    '--disable-features=BackForwardCache',
    ...(isRoot ? ['--no-sandbox'] : []),
    `--app=file://${REMOTE_HTML}`,
  ]
  const environment = [
    `HOME=${PROFILE}`,
    'PATH=/usr/local/bin:/usr/bin:/bin',
    'LANG=C.UTF-8',
    'DISPLAY=:0',
  ]
  const command = [
    'env -i',
    ...environment.map(shellQuote),
    shellQuote(CHROMIUM),
    ...flags.map(shellQuote),
    `>${shellQuote(`${PROFILE}/chromium.log`)} 2>&1`,
  ].join(' ')

  await sandbox.process.createSession(SESSION_ID)
  await sandbox.process.executeSessionCommand(SESSION_ID, { command, runAsync: true })

  const deadline = Date.now() + 60_000
  const probe = `curl -sf --max-time 2 -o /dev/null http://127.0.0.1:${port}/json/version`
  while (Date.now() < deadline) {
    const remainingSeconds = Math.max(1, Math.ceil((deadline - Date.now()) / 1000))
    const result = await sandbox.process.executeCommand(
      probe,
      undefined,
      undefined,
      remainingSeconds,
    )
    if (result.exitCode === 0) return
    await sleep(500)
  }

  throw new Error(
    `Chromium did not start in the sandbox. Last lines of ${PROFILE}/chromium.log:\n${await readChromiumLog(sandbox)}`,
  )
}

async function saveScreenshot(sandbox: Sandbox, outputPath: string): Promise<void> {
  const screenshot = await sandbox.computerUse.screenshot.takeFullScreen(false)
  if (!screenshot.screenshot) throw new Error('The sandbox returned an empty final screenshot')
  await writeFile(outputPath, Buffer.from(screenshot.screenshot, 'base64'))
  console.log(`screenshot: ${outputPath}`)
}

async function main(): Promise<void> {
  try {
    if (!(await stat(PAINT_HTML)).isFile()) throw new Error('not a file')
  } catch {
    throw new Error(
      `${PAINT_HTML} is missing. Run this example from its checkout: clone the repo, run npm install, then npm run start from this directory.`,
    )
  }

  const client = new Anthropic()
  const maxIterations = positiveInteger('MAX_TURNS', 120)
  const computer = await DaytonaComputer.create({ confirm, resolution: [WIDTH, HEIGHT] })
  try {
    console.log(`sandbox ${computer.sandbox.id}, screen ${computer.width}x${computer.height}`)
    await uploadSketchpad(computer.sandbox)
    await launchChromium(computer.sandbox)
    console.log(`sketchpad open at file://${REMOTE_HTML}; handing the desktop to the model`)

    let inputTokens = 0
    let outputTokens = 0
    let turns = 0
    const runner = client.beta.messages.toolRunner({
      model: process.env.MODEL ?? 'claude-sonnet-5-5',
      max_tokens: 4096,
      max_iterations: maxIterations,
      tools: [computer],
      messages: [{ role: 'user', content: TASK }],
    })
    for await (const message of runner) {
      turns += 1
      inputTokens += message.usage.input_tokens
      outputTokens += message.usage.output_tokens
      for (const block of message.content) {
        if (block.type === 'text') console.log(`[text] ${block.text}`)
        else if (block.type === 'tool_use') console.log(`[${block.name}] ${JSON.stringify(block.input)}`)
      }
    }

    const outputPath = process.env.OUTPUT_PATH
    if (outputPath) await saveScreenshot(computer.sandbox, outputPath)
    console.log(`turns: ${turns}`)
    console.log(`tokens: ${inputTokens} input, ${outputTokens} output`)
  } finally {
    await computer.close()
  }
}

main().catch((error: unknown) => {
  console.error(error)
  process.exitCode = 1
})
