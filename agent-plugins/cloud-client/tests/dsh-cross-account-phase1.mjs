import assert from 'node:assert/strict'
import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as CorePlugin from '../dist/client.js'

const serverUrl = process.env.DSH_TEST_SERVER_URL ?? 'https://cloud.seedvista.test'
const alicePassword = process.env.DSH_TEST_ALICE_PASSWORD
const bobPassword = process.env.DSH_TEST_BOB_PASSWORD
assert.ok(alicePassword, 'DSH_TEST_ALICE_PASSWORD is required')
assert.ok(bobPassword, 'DSH_TEST_BOB_PASSWORD is required')

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CorePlugin, { maxInlineBytes: 65536, maxTransferBytes: 8 * 1024 * 1024 })

const agents = {
  alice: { id: 'cross-account-alice' },
  bob: { id: 'cross-account-bob' },
}
const signal = new AbortController().signal
let sequence = 0

async function execute(agentName, name, args = {}) {
  return ctx.tools.execute({
    signal,
    callId: ToolCallId(`cross-${agentName}-${++sequence}`),
    name,
    arguments: args,
    agent: agents[agentName],
  })
}

async function call(agentName, name, args = {}) {
  const result = await execute(agentName, name, args)
  if (result.isError) throw new Error(`${agentName}:${name}: ${result.error.message}`)
  process.stdout.write(`PASS ${agentName}:${name} ${JSON.stringify(result.value)}\n`)
  return result.value
}

const isolated = await execute('bob', 'cloud_account')
assert.equal(isolated.isError, true)
assert.match(isolated.error.message, /NOT_LOGGED_IN/)
process.stdout.write('PASS per-agent credentials are isolated before Bob login\n')

await call('alice', 'cloud_login', { server_url: serverUrl, username: 'alice', password: alicePassword })
const stillIsolated = await execute('bob', 'cloud_account')
assert.equal(stillIsolated.isError, true)
assert.match(stillIsolated.error.message, /NOT_LOGGED_IN/)
process.stdout.write('PASS Alice login does not authenticate Bob agent\n')
await call('bob', 'cloud_login', { server_url: serverUrl, username: 'bob', password: bobPassword })

const stamp = `${Date.now()}-${process.pid}`
const root = `/dsh-cross-${stamp}`
const source = `${root}/cross-${stamp}.txt`
let shareId
try {
  await call('alice', 'cloud_upload', {
    remote_path: source,
    content: `message ${stamp} from alice to bob`,
    create_parents: true,
  })
  const shared = await call('alice', 'cloud_share', {
    remote_path: source,
    recipient: 'bob',
    share_type: 'user',
    permissions: ['read'],
    note: `cross-account-${stamp}`,
  })
  shareId = shared.shareId

  const incoming = await call('bob', 'cloud_list_shares', { direction: 'incoming', limit: 100 })
  const found = incoming.shares.find(item => item.shareId === shareId)
  assert.ok(found, `Bob did not discover incoming share ${shareId}`)
  assert.ok(found.targetPath, 'incoming share has no target path')
  const downloaded = await call('bob', 'cloud_download', { remote_path: found.targetPath, output: 'text' })
  assert.equal(downloaded.content, `message ${stamp} from alice to bob`)
  process.stdout.write(`PASS Bob discovered and downloaded Alice share ${shareId}\n`)
} finally {
  if (shareId) await call('alice', 'cloud_unshare', { share_id: shareId })
  await call('alice', 'cloud_delete', { remote_path: root })
  await call('alice', 'cloud_logout')
  await call('bob', 'cloud_logout')
}

process.stdout.write('PHASE1_CROSS_ACCOUNT_OK\n')
