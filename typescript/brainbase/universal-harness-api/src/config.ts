/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { AgentSpec } from './client.js'

// Base URL for the Brainbase API. Override with BRAINBASE_BASE_URL if needed.
export const BRAINBASE_BASE_URL = process.env.BRAINBASE_BASE_URL ?? 'https://api.brainbaselabs.com'

// The whole agent, described inline. Brainbase creates it, boots a sandbox on
// the chosen provider, and runs its turns — all from this one spec.
export const agent: AgentSpec = {
  // The harness that executes the agent's turns. Change this one line to run a
  // different harness on the same request: claude_code (default), codex,
  // cursor, factory, kafka_cloud, opencode, qoder, or qwen.
  harness: 'claude_code',

  // Run every agent in its own isolated Daytona sandbox. Daytona is also the
  // API default, so you get Daytona whether or not this is set — we set it
  // explicitly to make the choice clear.
  machine_kind: 'daytona',

  // The agent's system instructions — who it is and how it should work.
  instructions:
    'You are a precise coding assistant working inside a fresh Linux sandbox. ' +
    'Use the shell and filesystem to complete tasks, and keep your replies brief.',

  // Model the harness runs. Omit to use the harness default.
  model: 'claude-sonnet-5',

  // ---------------------------------------------------------------------------
  // Optional showcases — uncomment any of these to configure the sandbox and
  // the agent further. Each is planted before the agent runs its first tool.
  // ---------------------------------------------------------------------------

  // Bash that runs inside the Daytona sandbox before the agent launches:
  // install dependencies, clone a repo, warm a cache — whatever your agent
  // needs waiting for it. Runs with cwd=/workspace.
  // entrypoint: 'pip install -r requirements.txt',

  // Key–value secrets planted into the sandbox as plain environment variables,
  // available to the harness and to your entrypoint.
  // secrets: { TAVILY_API_KEY: process.env.TAVILY_API_KEY ?? '' },

  // MCP servers the agent can call — a remote `url` or an in-sandbox `command`.
  // mcp_servers: [{ name: 'search', url: 'https://mcp.example.com/sse' }],

  // Skills from the Brainbase registry, as `registry:creator/slug`.
  // skills: [{ source: 'registry:brainbase/deep-research' }],
}

// The first user message. The turn starts as soon as it is sent.
export const initialInput =
  'Create a file fib.py that prints the first 15 Fibonacci numbers on one line, ' +
  'run it with python3, and show me the output.'

// A follow-up sent on the same thread — same sandbox, full context.
export const followUpInput = 'Now change fib.py to print the first 30 numbers instead, and run it again.'
