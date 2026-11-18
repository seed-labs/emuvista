import assert from 'node:assert/strict'
import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as CorePlugin from '../dist/client.js'

const serverUrl = process.env.DSH_TEST_SERVER_URL ?? 'https://cloud.seedvista.test'
const username = process.env.DSH_TEST_USERNAME
const password = process.env.DSH_TEST_PASSWORD
const recipient = process.env.DSH_TEST_RECIPIENT
assert.ok(username, 'DSH_TEST_USERNAME is required')
assert.ok(password, 'DSH_TEST_PASSWORD is required')
assert.ok(recipient, 'DSH_TEST_RECIPIENT is required')

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CorePlugin, { maxInlineBytes: 65536, maxTransferBytes: 8 * 1024 * 1024 })

const agent = { id: `integration-${username}` }
const signal = new AbortController().signal
let sequence = 0

async function call(name, args = {}) {
  const result = await ctx.tools.execute({
    signal,
    callId: ToolCallId(`phase1-${username}-${++sequence}`),
    name,
    arguments: args,
    agent,
  })
  if (result.isError) throw new Error(`${name} failed through DSH ToolRuntime: ${result.error.message}`)
  process.stdout.write(`PASS ${name} ${JSON.stringify(result.value)}\n`)
  return result.value
}

async function expectFailure(name, args, pattern) {
  const result = await ctx.tools.execute({
    signal,
    callId: ToolCallId(`phase1-${username}-${++sequence}`),
    name,
    arguments: args,
    agent,
  })
  assert.equal(result.isError, true, `${name} unexpectedly succeeded`)
  assert.match(result.error.message, pattern)
  process.stdout.write(`PASS boundary ${name} -> ${result.error.message}\n`)
}

const stamp = `${Date.now()}-${process.pid}`
const root = `/dsh-phase1-${username}-${stamp}`
const nested = `${root}/messages/inbox`
const original = `${nested}/hello.txt`
const moved = `${nested}/renamed.txt`

await expectFailure('cloud_list', { remote_path: '/' }, /NOT_LOGGED_IN/)
await call('cloud_login', { server_url: serverUrl, username, password })
const account = await call('cloud_account')
assert.equal(account.username, username)

const created = await call('cloud_mkdir', { remote_path: nested, create_parents: true })
assert.equal(created.path, nested)
await expectFailure('cloud_mkdir', { remote_path: nested }, /ALREADY_EXISTS/)

await call('cloud_list', { remote_path: '/', limit: 1 })
const uploaded = await call('cloud_upload', {
  remote_path: original,
  content: `hello from ${username}`,
  encoding: 'utf8',
})
assert.equal(uploaded.created, true)
await expectFailure('cloud_upload', {
  remote_path: original,
  content: 'must not overwrite',
}, /PRECONDITION_FAILED/)

const metadata = await call('cloud_stat', { remote_path: original })
assert.equal(metadata.type, 'file')
assert.equal(metadata.etag, uploaded.etag)

const text = await call('cloud_download', { remote_path: original, output: 'text' })
assert.equal(text.content, `hello from ${username}`)
const base64 = await call('cloud_download', { remote_path: original, output: 'base64' })
assert.equal(Buffer.from(base64.content, 'base64').toString('utf8'), `hello from ${username}`)
const workspace = await call('cloud_download', {
  remote_path: original,
  output: 'workspace',
  local_name: `${username}-phase1.txt`,
})
assert.match(workspace.localPath, /dsh-cloud-downloads/)

await expectFailure('cloud_upload', {
  remote_path: original,
  content: 'wrong etag',
  overwrite: true,
  expected_etag: '"wrong"',
}, /PRECONDITION_FAILED/)
const overwritten = await call('cloud_upload', {
  remote_path: original,
  content: `updated by ${username}`,
  overwrite: true,
  expected_etag: metadata.etag,
})
assert.equal(overwritten.overwritten, true)

await expectFailure('cloud_move', {
  source_path: original,
  destination_path: original,
}, /must differ/)
await call('cloud_move', {
  source_path: original,
  destination_path: moved,
  overwrite: false,
})

const shared = await call('cloud_share', {
  remote_path: moved,
  recipient,
  share_type: 'user',
  permissions: ['read'],
  note: `phase1 from ${username}`,
})
assert.ok(shared.shareId)
const outgoing = await call('cloud_list_shares', { direction: 'outgoing' })
assert.ok(outgoing.shares.some(item => item.shareId === shared.shareId))
const updated = await call('cloud_update_share', {
  share_id: shared.shareId,
  permissions: ['read', 'update'],
  note: `updated phase1 from ${username}`,
})
assert.deepEqual(updated.permissions, ['read', 'update'])
await expectFailure('cloud_update_share', { share_id: shared.shareId }, /at least one/)
await call('cloud_unshare', { share_id: shared.shareId })

await expectFailure('cloud_delete', { remote_path: moved, expected_etag: '"wrong"' }, /ETAG_MISMATCH/)
await call('cloud_delete', { remote_path: root })
await call('cloud_logout')
await expectFailure('cloud_stat', { remote_path: '/' }, /NOT_LOGGED_IN/)
await call('cloud_logout')

process.stdout.write(`PHASE1_DSH_DISPATCH_OK ${username}\n`)
