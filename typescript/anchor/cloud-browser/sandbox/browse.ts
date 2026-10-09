/*
 * Copyright 2026 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

import { agentTask, client, Sessions } from 'anchorbrowser'

// The raw SDK reads ANCHORBROWSER_API_KEY. The host aliases it from ANCHOR_API_KEY.
client.setConfig({ auth: () => process.env.ANCHORBROWSER_API_KEY })

const session = await Sessions.createSession({
  body: {
    session: {
      timeout: { max_duration: 30, idle_timeout: 10 },
    },
  },
})

const sessionId = session.data?.id
const liveViewUrl = session.data?.live_view_url
if (!sessionId || !liveViewUrl) {
  throw new Error('Anchor session did not return an id and live view URL')
}

// cdp_url carries the API key in the query string. Print the live view only.
console.log(`Live view: ${liveViewUrl}`)

try {
  const result = await agentTask('Go to example.com and return the page title', {
    sessionId,
    taskOptions: { url: 'https://example.com' },
  })
  const value = result.data.result
  console.log(typeof value === 'string' ? value : JSON.stringify(value))
} finally {
  await Sessions.deleteSession({ path: { session_id: sessionId } })
}
