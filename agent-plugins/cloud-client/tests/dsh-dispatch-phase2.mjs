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
assert.ok(username && password && recipient, 'username, password, and recipient test variables are required')

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CorePlugin, { maxInlineBytes: 65536, maxTransferBytes: 8 * 1024 * 1024 })

const agent = { id: `phase2-${username}` }
const signal = new AbortController().signal
let sequence = 0
async function execute(name, args = {}) {
  return ctx.tools.execute({ signal, callId: ToolCallId(`phase2-${username}-${++sequence}`), name, arguments: args, agent })
}
async function call(name, args = {}) {
  const result = await execute(name, args)
  if (result.isError) throw new Error(`${name}: ${result.error.message}`)
  process.stdout.write(`PASS ${name} ${JSON.stringify(result.value)}\n`)
  return result.value
}
async function fail(name, args, pattern) {
  const result = await execute(name, args)
  assert.equal(result.isError, true, `${name} unexpectedly succeeded`)
  assert.match(result.error.message, pattern)
  process.stdout.write(`PASS boundary ${name} -> ${result.error.message}\n`)
}

await fail('cloud_copy', { source_path: '/a', destination_path: '/b' }, /NOT_LOGGED_IN/)
await call('cloud_login', { server_url: serverUrl, username, password })

const stamp = `${Date.now()}-${process.pid}`
const root = `/dsh-phase2-${username}-${stamp}`
const copiedRoot = `/dsh-phase2-tree-copy-${username}-${stamp}`
const source = `${root}/source-needle-${stamp}.txt`
const copied = `${root}/nested/copied-needle-${stamp}.txt`
let shareId
try {
  const uploaded = await call('cloud_upload', { remote_path: source, content: `phase2 ${username}`, create_parents: true })
  await fail('cloud_copy', { source_path: source, destination_path: source }, /must differ/)
  await fail('cloud_copy', { source_path: source, destination_path: copied, expected_etag: '"wrong"' }, /ETAG_MISMATCH/)
  const copy = await call('cloud_copy', {
    source_path: source, destination_path: copied, expected_etag: uploaded.etag, create_parents: true,
  })
  assert.equal(copy.copied, true)
  await fail('cloud_copy', { source_path: source, destination_path: copied }, /PRECONDITION_FAILED/)
  const replaced = await call('cloud_copy', { source_path: source, destination_path: copied, overwrite: true })
  assert.equal(replaced.overwritten, true)
  const treeCopy = await call('cloud_copy', { source_path: root, destination_path: copiedRoot })
  assert.equal(treeCopy.type, 'directory')
  const copiedContent = await call('cloud_download', {
    remote_path: `${copiedRoot}/nested/copied-needle-${stamp}.txt`, output: 'text',
  })
  assert.equal(copiedContent.content, `phase2 ${username}`)
  await fail('cloud_copy', { source_path: root, destination_path: `${root}/inside` }, /inside itself/)

  const search = await call('cloud_search', { query: `needle-${stamp}`, remote_path: root, item_type: 'file', limit: 20 })
  assert.ok(search.entries.some(item => item.path === source))
  assert.ok(search.entries.some(item => item.path === copied))
  const directoryOnly = await call('cloud_search', { query: `needle-${stamp}`, remote_path: root, item_type: 'directory' })
  assert.equal(directoryOnly.entries.length, 0)
  const future = await call('cloud_search', { query: `needle-${stamp}`, remote_path: root, modified_after: '2999-01-01T00:00:00Z' })
  assert.equal(future.entries.length, 0)
  await fail('cloud_search', { query: 'x', modified_after: 'not-a-date' }, /ISO-8601/)
  await fail('cloud_search', { query: 'x', item_type: 'device' }, /item_type/)

  const shared = await call('cloud_share', { remote_path: source, recipient, share_type: 'user', permissions: ['read'] })
  shareId = shared.shareId
  const detail = await call('cloud_get_share', { share_id: shareId })
  assert.equal(detail.shareId, shareId)
  assert.equal(detail.recipient, recipient)
  await fail('cloud_get_share', { share_id: '999999999' }, /(OCS_ERROR|not found|not exist)/i)

  const recipients = await call('cloud_search_recipients', { query: recipient, item_type: 'file', limit: 20 })
  assert.ok(recipients.recipients.some(item => item.recipient === recipient))
  const none = await call('cloud_search_recipients', { query: `nobody-${stamp}`, limit: 20 })
  assert.equal(none.recipients.length, 0)
  await fail('cloud_search_recipients', { query: recipient, item_type: 'device' }, /item_type/)
} finally {
  if (shareId) await call('cloud_unshare', { share_id: shareId })
  const copiedRootStat = await execute('cloud_stat', { remote_path: copiedRoot })
  if (!copiedRootStat.isError) await call('cloud_delete', { remote_path: copiedRoot })
  await call('cloud_delete', { remote_path: root })
  await call('cloud_logout')
}

process.stdout.write(`PHASE2_DSH_DISPATCH_OK ${username}\n`)
