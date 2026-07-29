/*
 * Copyright 2025 Daytona Platforms Inc.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Local pairing proxy (runs inside the Daytona sandbox).
 *
 * Why this exists: OpenClaw silently auto-approves Control UI device pairing
 * for clean LOCAL connections (loopback peer, no forwarded identity headers)
 * once gateway token auth has succeeded. Daytona's preview proxy adds
 * X-Forwarded-For, which makes browsers look remote and forces a manual
 * device-approval step. This proxy sits between them and removes the
 * forwarding/identity headers, so preview visitors are treated as local and
 * pair silently on their first attempt.
 *
 * Security notes:
 * - Token auth still runs before pairing, so this is not an auth bypass; the
 *   tokenized preview URL remains the credential that gates access.
 * - Identity headers are stripped (not rewritten) so nothing downstream can be
 *   spoofed through this hop. The trade-off is that the gateway sees 127.0.0.1
 *   as the client IP for every request, so its logs and per-IP rate limiting
 *   can no longer distinguish callers.
 * - Both listeners bind loopback only: nothing here is directly reachable from
 *   outside the sandbox.
 *
 * Usage: node local-pairing-proxy.cjs <listenPort> <gatewayPort>
 */

const http = require('http')
const net = require('net')

const LISTEN_PORT = Number(process.argv[2])
const GATEWAY_PORT = Number(process.argv[3])

const isValidPort = (value) => Number.isInteger(value) && value >= 1 && value <= 65535

if (!isValidPort(LISTEN_PORT) || !isValidPort(GATEWAY_PORT)) {
  console.error('usage: node local-pairing-proxy.cjs <listenPort> <gatewayPort> (1-65535)')
  process.exit(1)
}

// Headers that assert a client identity on behalf of an upstream proxy. The
// gateway treats their absence as proof of a direct local caller, so they must
// never survive this hop.
const STRIPPED_HEADERS = new Set([
  'forwarded',
  'x-real-ip',
  'tailscale-user-login',
  'tailscale-user-name',
  'tailscale-user-profile-pic',
])

function isStripped(name) {
  const lower = name.toLowerCase()
  return STRIPPED_HEADERS.has(lower) || lower.startsWith('x-forwarded-')
}

function sanitizeHeaders(headers) {
  const out = {}
  for (const name of Object.keys(headers)) {
    if (isStripped(name)) continue
    out[name] = headers[name]
  }
  return out
}

// Plain HTTP: static Control UI assets and JSON endpoints.
const server = http.createServer((req, res) => {
  const upstream = http.request(
    {
      host: '127.0.0.1',
      port: GATEWAY_PORT,
      method: req.method,
      path: req.url,
      headers: sanitizeHeaders(req.headers),
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers)
      upstreamRes.pipe(res)
    },
  )
  upstream.on('error', () => {
    res.writeHead(502)
    res.end('gateway unavailable')
  })
  req.pipe(upstream)
})

// WebSocket upgrades: the Control UI's live gateway connection.
//
// A WebSocket starts as an ordinary HTTP/1.1 GET carrying `Connection: Upgrade`.
// Once the server answers `101 Switching Protocols` the socket stops being HTTP
// and becomes a raw two-way byte pipe, so Node does not route these through the
// normal request handler: it hands us the raw socket here instead. That means we
// cannot reuse http.request() and must replay the handshake ourselves, then just
// relay bytes. `head` holds any bytes that arrived in the same packet after the
// headers (the first protocol data) and must not be dropped.
server.on('upgrade', (req, socket, head) => {
  const headers = sanitizeHeaders(req.headers)
  const lines = [`${req.method} ${req.url} HTTP/1.1`]
  for (const name of Object.keys(headers)) {
    const value = headers[name]
    for (const item of Array.isArray(value) ? value : [value]) {
      // Header blocks are CR/LF-delimited text and we are writing them by hand,
      // so a value containing CR/LF could close its own line and inject extra
      // headers - re-adding an identity header sanitizeHeaders just removed - or
      // end the block and smuggle a second request past this hop. Node's parser
      // normally rejects such values already; fail closed rather than rely on it.
      if (typeof item !== 'string' || /[\r\n]/.test(item)) {
        socket.destroy()
        return
      }
      lines.push(`${name}: ${item}`)
    }
  }

  const upstream = net.connect(GATEWAY_PORT, '127.0.0.1', () => {
    upstream.write(`${lines.join('\r\n')}\r\n\r\n`) // blank line terminates the header block
    if (head && head.length) upstream.write(head)
    // From here this is a dumb relay: the 101 response and every WebSocket
    // frame flow through untouched. Frames are never parsed.
    socket.pipe(upstream)
    upstream.pipe(socket)
  })
  // Tear down the peer so a half-open connection cannot leak.
  upstream.on('error', () => socket.destroy())
  socket.on('error', () => upstream.destroy())
})

server.listen(LISTEN_PORT, '127.0.0.1', () => {
  console.log(`local pairing proxy listening on 127.0.0.1:${LISTEN_PORT} -> 127.0.0.1:${GATEWAY_PORT}`)
})
