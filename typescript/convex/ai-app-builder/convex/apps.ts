import { v } from 'convex/values'
import { internalMutation, internalQuery, query } from './_generated/server'

export const list = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query('apps').order('desc').take(50)
  },
})

export const getInternal = internalQuery({
  args: { appId: v.id('apps') },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.appId)
  },
})

/**
 * Atomically claim an app for iteration. Mutations are serializable, so two
 * concurrent follow-ups can't both pass the status check — the loser throws
 * instead of silently overwriting the winner's generation.
 */
export const beginIterate = internalMutation({
  args: { appId: v.id('apps') },
  handler: async (ctx, args) => {
    const app = await ctx.db.get(args.appId)
    if (!app?.sandboxId || !app.code) throw new Error('App is not ready yet')
    const canIterate = app.status === 'ready' || app.status === 'error'
    if (!canIterate) throw new Error(`App is busy (status: ${app.status})`)
    await ctx.db.patch(args.appId, { status: 'generating code' })
    return app
  },
})

export const create = internalMutation({
  args: { prompt: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db.insert('apps', {
      prompt: args.prompt,
      status: 'creating sandbox',
    })
  },
})

export const update = internalMutation({
  args: {
    appId: v.id('apps'),
    status: v.optional(
      v.union(
        v.literal('creating sandbox'),
        v.literal('generating code'),
        v.literal('writing files'),
        v.literal('installing dependencies'),
        v.literal('starting dev server'),
        v.literal('ready'),
        v.literal('error'),
      ),
    ),
    sandboxId: v.optional(v.string()),
    previewUrl: v.optional(v.string()),
    code: v.optional(v.string()),
    draftCode: v.optional(v.string()),
    error: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { appId, ...fields } = args
    const defined = Object.fromEntries(
      Object.entries(fields).filter(([, value]) => value !== undefined),
    )
    await ctx.db.patch(appId, defined)
  },
})
