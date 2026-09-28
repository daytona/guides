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
