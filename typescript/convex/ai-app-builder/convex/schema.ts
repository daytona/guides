import { defineSchema, defineTable } from 'convex/server'
import { v } from 'convex/values'

export default defineSchema({
  // One row per generated app. Every status change is a plain document patch —
  // the UI subscribes with useQuery and re-renders on each step automatically.
  apps: defineTable({
    prompt: v.string(),
    status: v.union(
      v.literal('creating sandbox'),
      v.literal('generating code'),
      v.literal('writing files'),
      v.literal('installing dependencies'),
      v.literal('starting dev server'),
      v.literal('ready'),
      v.literal('error'),
    ),
    sandboxId: v.optional(v.string()),
    previewUrl: v.optional(v.string()),
    /** Current App.jsx source — context for follow-up edit prompts. */
    code: v.optional(v.string()),
    /** Partial code streamed during generation — the UI renders it live. */
    draftCode: v.optional(v.string()),
    error: v.optional(v.string()),
  }),
})
