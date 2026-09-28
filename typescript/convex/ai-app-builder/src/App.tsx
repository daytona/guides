import { useAction, useQuery } from 'convex/react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../convex/_generated/api'
import type { Doc } from '../convex/_generated/dataModel'

const BUILD_STEPS = [
  'creating sandbox',
  'generating code',
  'writing files',
  'installing dependencies',
  'starting dev server',
  'ready',
] as const

export default function App() {
  // Reactive: every status patch the backend makes re-renders this list live.
  const apps = useQuery(api.apps.list) ?? []
  const build = useAction(api.builder.build)
  const [prompt, setPrompt] = useState('')
  const [building, setBuilding] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!prompt.trim() || building) return
    setBuilding(true)
    setPrompt('')
    try {
      await build({ prompt: prompt.trim() })
    } catch {
      // The app card shows the error state reactively.
    } finally {
      setBuilding(false)
    }
  }

  return (
    <main>
      <header>
        <h1>AI App Builder</h1>
        <p>
          Describe an app. An LLM writes it, a <a href="https://www.daytona.io">Daytona</a>{' '}
          sandbox runs it, and <a href="https://www.convex.dev">Convex</a> streams every build
          step to this page — try refreshing mid-build.
        </p>
      </header>

      <form onSubmit={onSubmit}>
        <input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="e.g. a pomodoro timer with a circular progress ring"
          autoFocus
        />
        <button type="submit" disabled={building || !prompt.trim()}>
          {building ? 'Building…' : 'Build it'}
        </button>
      </form>

      <section className="apps">
        {apps.length === 0 && <p className="empty">No apps yet — build your first one.</p>}
        {apps.map((app) => (
          <AppCard key={app._id} app={app} />
        ))}
      </section>
    </main>
  )
}

function CodeStream({ code }: { code: string }) {
  // Pin the view to the newest lines as the code streams in.
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [code])
  return (
    <pre ref={ref} className="code-stream">
      {code}
    </pre>
  )
}

function AppCard({ app }: { app: Doc<'apps'> }) {
  const iterate = useAction(api.builder.iterate)
  const [instruction, setInstruction] = useState('')
  const currentStep = BUILD_STEPS.indexOf(app.status as (typeof BUILD_STEPS)[number])

  async function onIterate(event: React.FormEvent) {
    event.preventDefault()
    if (!instruction.trim()) return
    const value = instruction.trim()
    setInstruction('')
    await iterate({ appId: app._id, instruction: value }).catch(() => {})
  }

  return (
    <article className="card">
      <div className="card-head">
        <span className="prompt">{app.prompt}</span>
        <span className={`status status-${app.status === 'ready' ? 'ready' : app.status === 'error' ? 'error' : 'busy'}`}>
          {app.status}
        </span>
      </div>

      {app.status !== 'ready' && app.status !== 'error' && (
        <ol className="steps">
          {BUILD_STEPS.slice(0, -1).map((step, index) => (
            <li
              key={step}
              className={index < currentStep ? 'done' : index === currentStep ? 'active' : ''}
            >
              {step}
            </li>
          ))}
        </ol>
      )}

      {app.status === 'generating code' && app.draftCode && (
        <CodeStream code={app.draftCode} />
      )}

      {app.status === 'error' && <pre className="error">{app.error}</pre>}

      {app.previewUrl && (
        <>
          <iframe src={app.previewUrl} title={app.prompt} />
          <div className="card-foot">
            <form onSubmit={onIterate}>
              <input
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="Change something… e.g. make it dark mode"
              />
              <button type="submit" disabled={app.status !== 'ready' || !instruction.trim()}>
                Update
              </button>
            </form>
            <a href={app.previewUrl} target="_blank" rel="noreferrer">
              Open ↗
            </a>
          </div>
        </>
      )}
    </article>
  )
}
