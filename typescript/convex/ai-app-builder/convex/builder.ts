import { createOpenAI } from '@ai-sdk/openai'
import { Daytona } from '@daytona/convex'
import { streamText } from 'ai'
import { v } from 'convex/values'
import { components, internal } from './_generated/api'
import { action, type ActionCtx } from './_generated/server'
import type { Doc, Id } from './_generated/dataModel'
import { APP_DIR, DEV_PORT, SCAFFOLD_FILES, SYSTEM_PROMPT } from './scaffold'

const daytona = new Daytona(components.daytona)

/**
 * Stream the generation, patching partial code into the app row every ~300ms.
 * Convex reactivity fans each patch out to every subscribed client, so the
 * code visibly writes itself in the UI — durably: refresh mid-stream and it
 * resumes, because the stream lives in the database, not a socket.
 */
async function generateAppCode(
  ctx: ActionCtx,
  appId: Id<'apps'>,
  prompt: string,
  abortSignal?: AbortSignal,
): Promise<string> {
  const openai = createOpenAI({ apiKey: process.env.OPENAI_API_KEY })
  const result = streamText({
    model: openai('gpt-5.4'),
    system: SYSTEM_PROMPT,
    prompt,
    abortSignal,
  })

  let draft = ''
  let lastPatch = 0
  for await (const chunk of result.textStream) {
    draft += chunk
    if (Date.now() - lastPatch > 300) {
      lastPatch = Date.now()
      await ctx.runMutation(internal.apps.update, { appId, draftCode: draft })
    }
  }

  const text = await result.text
  return text.replace(/^```[a-z]*\n?/, '').replace(/\n?```\s*$/, '')
}

type AppUpdate = {
  status?: Doc<'apps'>['status']
  sandboxId?: string
  previewUrl?: string
  code?: string
  draftCode?: string
  error?: string
}

async function setStatus(ctx: ActionCtx, appId: Id<'apps'>, fields: AppUpdate) {
  await ctx.runMutation(internal.apps.update, { appId, ...fields })
}

/** Generate an app from a prompt: sandbox -> code -> files -> install -> dev server -> preview URL. */
export const build = action({
  args: { prompt: v.string() },
  handler: async (ctx, args) => {
    const appId: Id<'apps'> = await ctx.runMutation(internal.apps.create, {
      prompt: args.prompt,
    })
    try {
      // Kick off sandbox creation and code generation in parallel — the UI
      // shows each step live because every setStatus patch is reactive. If
      // sandbox creation fails, abort the LLM stream so tokens stop flowing
      // into an app that's already doomed.
      const abort = new AbortController()
      const sandboxPromise = daytona
        .createSandbox(ctx, {
          labels: { 'created-by': 'convex-ai-app-builder' },
          autoStopInterval: 15,
          autoDeleteInterval: 120,
        })
        .catch((error) => {
          abort.abort()
          throw error
        })
      await setStatus(ctx, appId, { status: 'generating code' })
      const [{ sandboxId }, code] = await Promise.all([
        sandboxPromise,
        generateAppCode(ctx, appId, args.prompt, abort.signal),
      ])
      await setStatus(ctx, appId, {
        sandboxId,
        code,
        draftCode: '',
        status: 'writing files',
      })

      for (const [path, content] of Object.entries(SCAFFOLD_FILES)) {
        await daytona.writeFile(ctx, {
          sandboxId,
          path: `${APP_DIR}/${path}`,
          content,
        })
      }
      await daytona.writeFile(ctx, {
        sandboxId,
        path: `${APP_DIR}/src/App.jsx`,
        content: code,
      })

      await setStatus(ctx, appId, { status: 'installing dependencies' })
      const install = await daytona.run(ctx, {
        sandboxId,
        command: 'npm install --no-audit --no-fund',
        cwd: APP_DIR,
        timeoutSeconds: 300,
      })
      if (install.exitCode !== 0) {
        throw new Error(`npm install failed: ${install.result.slice(-500)}`)
      }

      await setStatus(ctx, appId, { status: 'starting dev server' })
      // The dev server outlives this action, so background it with its output
      // redirected — then poll until it accepts connections.
      await daytona.run(ctx, {
        sandboxId,
        command: `nohup npm run dev > /tmp/dev.log 2>&1 &`,
        cwd: APP_DIR,
      })
      const wait = await daytona.run(ctx, {
        sandboxId,
        command: `for i in $(seq 1 60); do curl -sf -o /dev/null http://localhost:${DEV_PORT} && exit 0; sleep 1; done; cat /tmp/dev.log; exit 1`,
        timeoutSeconds: 90,
      })
      if (wait.exitCode !== 0) {
        throw new Error(`dev server failed to start: ${wait.result.slice(-500)}`)
      }

      const preview = await daytona.getPreviewUrl(ctx, {
        sandboxId,
        port: DEV_PORT,
        expiresInSeconds: 60 * 60 * 24,
      })
      await setStatus(ctx, appId, { previewUrl: preview.url, status: 'ready' })
      return { appId, previewUrl: preview.url }
    } catch (error) {
      await setStatus(ctx, appId, {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      })
      throw error
    }
  },
})

/** Apply a follow-up instruction: regenerate App.jsx — Vite hot-reloads the preview. */
export const iterate = action({
  args: { appId: v.id('apps'), instruction: v.string() },
  handler: async (ctx, args) => {
    // Atomic claim: checks readiness and flips status in one transaction, so
    // concurrent follow-ups can't generate from the same base code.
    const app = await ctx.runMutation(internal.apps.beginIterate, {
      appId: args.appId,
    })
    try {
      const code = await generateAppCode(
        ctx,
        args.appId,
        `Here is the current src/App.jsx:\n\n${app.code}\n\nApply this change and output the complete updated file:\n${args.instruction}`,
      )
      // The sandbox pauses after 15 idle minutes; restart it if needed before
      // writing (writeFile doesn't auto-start the way run does).
      await daytona.startSandbox(ctx, { sandboxId: app.sandboxId! })
      await daytona.writeFile(ctx, {
        sandboxId: app.sandboxId!,
        path: `${APP_DIR}/src/App.jsx`,
        content: code,
      })
      await setStatus(ctx, args.appId, { code, draftCode: '', status: 'ready' })
    } catch (error) {
      await setStatus(ctx, args.appId, {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      })
      throw error
    }
  },
})
