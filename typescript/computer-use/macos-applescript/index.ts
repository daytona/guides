/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { Computer, MacOSSandbox } from 'use-computer-sdk'
import Anthropic from '@anthropic-ai/sdk'
import * as dotenv from 'dotenv'
import * as fs from 'fs'

dotenv.config()

const MODEL = 'claude-opus-5'

// Helper function to extract AppleScript from a given string
function extractAppleScript(text: string): string {
  const m = text.match(/```(?:applescript)?([\s\S]*?)```/)
  return (m ? m[1] : text).trim()
}

// Make sure you have the USE_COMPUTER_API_KEY and ANTHROPIC_API_KEY environment variables set
const computer = new Computer()
const anthropic = new Anthropic()

async function run() {
  let mac: MacOSSandbox | null = null
  let recordingId: string | null = null

  try {
    // Reserve a Mac Mini and create a macOS sandbox on it
    console.log('Reserving a macOS sandbox...')
    const reservation = await computer.reserve({ hours: 1 })
    mac = await computer.create({ type: 'macos', reservationId: reservation.id })
    console.log('Sandbox ready. Watch it live at:', mac.vncUrl)

    // Start recording the screen before doing anything, so the whole run is captured
    recordingId = await mac.recording.start()
    console.log('Recording started:', recordingId)

    // Define the task in plain English
    const task = 'Open TextEdit, create a new document, and type a haiku about cloud computing.'
    console.log('Task:', task)

    // Generate the AppleScript with the LLM
    console.log('Generating AppleScript...')
    const systemPrompt = `You are a macOS automation assistant.
Given a task, respond with a single AppleScript code block (\`\`\`applescript ... \`\`\`) that performs it using "System Events" and native app scripting.
Add short delays between steps so the UI has time to catch up.
Only output the code block, nothing else.`
    const llmResponse = await anthropic.messages.create({
      model: MODEL,
      max_tokens: 1024,
      system: systemPrompt,
      messages: [{ role: 'user', content: task }],
    })
    const llmText = llmResponse.content
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('\n')
    const script = extractAppleScript(llmText)
    console.log(script)

    // Upload and run the AppleScript inside the sandbox
    console.log('Running AppleScript...')
    await mac.upload(Buffer.from(script), '/tmp/task.applescript')
    const exec = await mac.execSsh('osascript /tmp/task.applescript')
    console.log('Output:', exec.stdout || '(no output)')
    if (exec.exitCode !== 0) console.error('Error:', exec.stderr)

    // Give the sandbox a moment so the final UI state is visible in the recording
    await new Promise((resolve) => setTimeout(resolve, 2000))
  } catch (error) {
    console.error('Error executing example:', error)
  } finally {
    // Stop the recording and download it, even if something above failed
    if (mac && recordingId) {
      console.log('Stopping recording...')
      const recording = await mac.recording.stop(recordingId)
      const bytes = await mac.recording.download(recording.recordingId)
      fs.writeFileSync('recording.mp4', bytes)
      console.log('✓ Recording saved to recording.mp4')
    }

    // Always tear down the sandbox
    if (mac) {
      await mac.close()
    }
  }
}

run()
