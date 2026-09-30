/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

// Event shapes emitted by `goose run --output-format stream-json` (newline-delimited JSON).

export interface GooseEvent {
  type: string
}

export interface GooseTextBlock {
  type: 'text'
  text: string
}

export interface GooseToolUseBlock {
  type: 'tool_use'
  id: string
  name: string
  input?: Record<string, unknown>
}

export interface GooseToolResultBlock {
  type: 'tool_result'
  tool_use_id: string
  content?: string | Array<{ type: string; text?: string }>
  is_error?: boolean
}

export type GooseContentBlock = GooseTextBlock | GooseToolUseBlock | GooseToolResultBlock

// A single turn of the conversation. Goose has no dedicated session-init event, so
// there is no session/thread ID to capture here (see session.ts for how resume works).
export interface GooseMessageEvent extends GooseEvent {
  type: 'message'
  message: {
    role: 'assistant' | 'user'
    content: GooseContentBlock[]
  }
}

// Marks the end of a turn. Goose emits this even when the turn itself failed (see the
// wrapped-error handling in session.ts), so it does not by itself mean "success".
export interface GooseCompleteEvent extends GooseEvent {
  type: 'complete'
}

export interface GooseErrorEvent extends GooseEvent {
  type: 'error'
  error: string | { message: string; code?: string }
}
