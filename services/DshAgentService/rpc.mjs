import { readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'

const [port, log, method] = process.argv.slice(1)
let token
try {
  const text = readFileSync(log, 'utf8')
  token = [...text.matchAll(/https?:\/\/[^\s]+\/\?token=([^\s&]+)/g)].at(-1)?.[1]
} catch {
  // A missing log typically means Web has not started.
}

function output(value) {
  console.log(JSON.stringify(value))
}

if (!token) {
  output({ error: 'web_not_ready' })
} else {
  const base = 'http://127.0.0.1:' + port
  const signal = AbortSignal.timeout(120000)
  try {
    const auth = await fetch(base + '/?token=' + token, { redirect: 'manual', signal })
    const cookie = auth.headers.getSetCookie().map(value => value.split(';', 1)[0]).join('; ')
    if (!cookie) {
      output({ error: 'authentication_failed' })
    } else {
      let body = ''
      for await (const chunk of process.stdin) body += chunk
      const args = JSON.parse(body)
      const envelope = { type: 'client-request', rpcId: randomUUID(), method, payload: { args } }
      const response = await fetch(base + '/api/' + method, {
        method: 'POST', signal, headers: { cookie, 'content-type': 'application/json' },
        body: JSON.stringify(envelope),
      })
      if (response.status === 401 || response.status === 403) {
        output({ error: 'authentication_failed' })
      } else if (!response.ok) {
        output({ error: 'rpc_http_error' })
      } else {
        const { result } = await response.json()
        output(result.ok ? { value: result.value } : { error: result.error?.code ?? 'rpc_error' })
      }
    }
  } catch {
    output({ error: 'disconnected' })
  }
}
