/*
 * Copyright Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

// Event shapes emitted by `goose run --output-format stream-json` (newline-delimited JSON).
// Mirrors the CLI's `StreamEvent` enum and the message content blocks it serializes:
// https://github.com/aaif-goose/goose/blob/main/crates/goose-cli/src/session/mod.rs

export interface GooseEvent {
  type: string
}

// Goose wraps tool calls and tool results as `{ status: "success", value }` or
// `{ status: "error", error }`.
export type GooseToolResult<T> = { status: 'success'; value: T } | { status: 'error'; error: string }

export interface GooseTextBlock {
  type: 'text'
  text: string
}

export interface GooseToolRequestBlock {
  type: 'toolRequest'
  id: string
  toolCall: GooseToolResult<{ name: string; arguments?: Record<string, unknown> }>
}

export interface GooseToolResponseBlock {
  type: 'toolResponse'
  id: string
  toolResult: GooseToolResult<{ content: Array<{ type: string; text?: string }>; isError?: boolean }>
}

// Goose also emits thinking, error and system-notification blocks; the session ignores them.
export type GooseContentBlock = GooseTextBlock | GooseToolRequestBlock | GooseToolResponseBlock

// Assistant messages carry the reply text (streamed: each chunk arrives as its own event)
// and tool requests; tool responses come back in user messages. Goose has no session-init
// event, so there is no session ID to capture (see session.ts for how resume works).
export interface GooseMessageEvent extends GooseEvent {
  type: 'message'
  message: {
    role: 'assistant' | 'user'
    content: GooseContentBlock[]
  }
}

// Marks the end of a successful turn.
export interface GooseCompleteEvent extends GooseEvent {
  type: 'complete'
}

// Marks the end of a failed turn (for example a rejected API key); no `complete` follows.
export interface GooseErrorEvent extends GooseEvent {
  type: 'error'
  error: string
}
