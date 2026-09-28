/**
 * Fixed Vite + React scaffold written into every sandbox. The LLM only ever
 * generates src/App.jsx — keeping generations fast, cheap, and reliable while
 * Vite's file watcher gives us hot reload when follow-up edits rewrite it.
 */

export const APP_DIR = '/home/daytona/app'
export const DEV_PORT = 3000

export const SCAFFOLD_FILES: Record<string, string> = {
  'package.json': JSON.stringify(
    {
      name: 'generated-app',
      private: true,
      type: 'module',
      scripts: { dev: 'vite' },
      dependencies: {
        react: '^19.0.0',
        'react-dom': '^19.0.0',
      },
      devDependencies: {
        '@vitejs/plugin-react': '^5.0.0',
        vite: '^7.0.0',
      },
    },
    null,
    2,
  ),
  'vite.config.js': `import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: ${DEV_PORT},
    strictPort: true,
    // Vite rejects requests whose Host header isn't localhost (DNS-rebinding
    // protection). Daytona's preview proxy forwards the public preview domain
    // as the Host, so allow it. Not CORS — a server-side Host allowlist.
    allowedHosts: true,
  },
})
`,
  'index.html': `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Generated App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
`,
  'src/main.jsx': `import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
`,
}

export const SYSTEM_PROMPT = `You generate a single React component file for a Vite + React 19 project.

Rules:
- Output ONLY the complete contents of src/App.jsx — no markdown fences, no explanations.
- Default-export a component named App.
- Plain JavaScript + JSX (no TypeScript). Only react and react-dom are installed — import anything you use from 'react' (e.g. import { useState, useEffect } from 'react'); never import any other package.
- All styling must be inline style objects or a <style> tag rendered by the component. Make it polished and modern: real layout, spacing, a coherent color scheme.
- The app must be fully self-contained and interactive where it makes sense (useState/useEffect are encouraged).`
