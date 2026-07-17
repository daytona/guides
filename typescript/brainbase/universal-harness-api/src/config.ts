/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { AgentSpec } from './client.js'

// Base URL for the Brainbase API. Override with BRAINBASE_BASE_URL if needed.
export const BRAINBASE_BASE_URL = process.env.BRAINBASE_BASE_URL ?? 'https://api.brainbaselabs.com'

// Bash that runs inside the Daytona sandbox before the agent launches (cwd is
// /workspace). `set -e` makes any failed step fail the whole entrypoint instead
// of being masked by a later one. It seeds a tiny Python project with a
// deliberately failing test suite — the "ticket" the agent picks up — then
// installs the test runner last, so a failed install surfaces without skipping
// the seeding. The bug: merge_intervals uses `<` where it should use `<=`, so
// touching intervals like (1, 2) and (2, 3) are not merged and two of the five
// tests fail.
const seedEntrypoint = `set -e
cat > /workspace/intervals.py <<'PY'
def merge_intervals(intervals):
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start < last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
PY
cat > /workspace/test_intervals.py <<'PY'
from intervals import merge_intervals


def test_overlapping():
    assert merge_intervals([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_touching_intervals_merge():
    assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]


def test_unsorted_input():
    assert merge_intervals([(2, 3), (1, 2)]) == [(1, 3)]


def test_empty():
    assert merge_intervals([]) == []


def test_single():
    assert merge_intervals([(5, 7)]) == [(5, 7)]
PY
python3 -m pip install -q pytest`

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
    'You are a background software engineering agent working in a fresh Linux sandbox that ' +
    'already contains a small Python project. Fix failing tests by editing the implementation ' +
    'only — never modify the test files. Run pytest to verify, and iterate until the whole ' +
    'suite passes. Keep your replies brief.',

  // Model the harness runs. Omit to use the harness default.
  model: 'claude-sonnet-5',

  // Prepare the sandbox before the agent starts: install pytest and seed the
  // project the agent will work on (see seedEntrypoint above).
  entrypoint: seedEntrypoint,

  // ---------------------------------------------------------------------------
  // More optional showcases — uncomment any of these to configure the sandbox
  // and the agent further.
  // ---------------------------------------------------------------------------

  // Key–value secrets planted into the sandbox as plain environment variables,
  // available to the harness and to your entrypoint.
  // secrets: { TAVILY_API_KEY: process.env.TAVILY_API_KEY ?? '' },

  // MCP servers the agent can call — a remote `url` or an in-sandbox `command`.
  // mcp_servers: [{ name: 'search', url: 'https://mcp.example.com/sse' }],

  // Skills from the Brainbase registry, as `registry:creator/slug`.
  // skills: [{ source: 'registry:brainbase/deep-research' }],
}

// The first user message — a real ticket: a failing test suite to fix. The turn
// starts as soon as it is sent.
export const initialInput =
  'The Python project in /workspace has a failing test suite. Run pytest to see the failures, ' +
  'then find and fix the bug in intervals.py so the whole suite passes. Do not modify the tests.'

// A follow-up sent on the same thread — same sandbox, full context. It extends
// the module the agent just fixed and re-runs the suite.
export const followUpInput =
  'Add a function total_covered(intervals) to intervals.py that returns the total length covered ' +
  'by the intervals (merge overlapping ones first), add tests for it, and run pytest again.'
