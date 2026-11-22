import assert from 'node:assert/strict'
import { setTimeout as delay } from 'node:timers/promises'
import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as CorePlugin from '../dist/client.js'

const serverUrl = process.env.DSH_TEST_SERVER_URL ?? 'https://cloud.seedvista.test'
const username = process.env.DSH_TEST_USERNAME
const password = process.env.DSH_TEST_PASSWORD
assert.ok(username && password, 'username and password test variables are required')

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CorePlugin, { maxInlineBytes: 65536, maxTransferBytes: 8 * 1024 * 1024 })

const agent = { id: `phase3-${username}` }
const signal = new AbortController().signal
let sequence = 0
async function execute(name, args = {}) {
  return ctx.tools.execute({ signal, callId: ToolCallId(`phase3-${username}-${++sequence}`), name, arguments: args, agent })
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

await fail('cloud_list_trash', {}, /NOT_LOGGED_IN/)
await call('cloud_login', { server_url: serverUrl, username, password })
const stamp = `${Date.now()}-${process.pid}`
const root = `/dsh-phase3-${username}-${stamp}`
const trashPath = `${root}/trash-${stamp}.txt`
const versionPath = `${root}/version-${stamp}.txt`

const findTrash = async path => {
  const expected = path.replace(/^\//, '')
  const listing = await call('cloud_list_trash', { limit: 200 })
  return listing.items
    .filter(item => item.originalLocation === expected || item.originalLocation === path || item.name === path.split('/').at(-1))
    .sort((a, b) => String(b.deletedAt).localeCompare(String(a.deletedAt)))[0]
}

try {
  await call('cloud_upload', { remote_path: trashPath, content: `restore-${stamp}`, create_parents: true })
  await call('cloud_delete', { remote_path: trashPath })
  const recoverable = await findTrash(trashPath)
  assert.ok(recoverable?.trashId, `deleted item ${trashPath} was not present in trash`)
  await fail('cloud_restore_trash', { trash_id: '../escape' }, /opaque identifier/)
  const restored = await call('cloud_restore_trash', { trash_id: recoverable.trashId })
  assert.equal(restored.restoredPath, trashPath)
  const restoredContent = await call('cloud_download', { remote_path: trashPath, output: 'text' })
  assert.equal(restoredContent.content, `restore-${stamp}`)

  await call('cloud_delete', { remote_path: trashPath })
  const disposable = await findTrash(trashPath)
  assert.ok(disposable?.trashId, 'second deleted item was not present in trash')
  await call('cloud_delete_permanently', { trash_id: disposable.trashId })
  const afterPermanent = await call('cloud_list_trash', { limit: 200 })
  assert.ok(!afterPermanent.items.some(item => item.trashId === disposable.trashId))
  await fail('cloud_delete_permanently', { trash_id: 'missing-trash-id-999999' }, /(HTTP_ERROR|404|not found)/i)

  let uploaded = await call('cloud_upload', { remote_path: versionPath, content: `version-one-${stamp}` })
  await delay(2500)
  uploaded = await call('cloud_upload', {
    remote_path: versionPath, content: `version-two-${stamp}`, overwrite: true, expected_etag: uploaded.etag,
  })
  let versions = await call('cloud_list_versions', { remote_path: versionPath, limit: 200 })
  for (let attempt = 0; versions.versions.length === 0 && attempt < 3; attempt++) {
    await delay(2500)
    uploaded = await call('cloud_upload', {
      remote_path: versionPath, content: `version-later-${attempt}-${stamp}`, overwrite: true, expected_etag: uploaded.etag,
    })
    versions = await call('cloud_list_versions', { remote_path: versionPath, limit: 200 })
  }
  assert.ok(versions.versions.length > 0, 'Nextcloud did not retain any historical version')
  assert.ok(versions.versions.some(item => item.source === 'managed'), 'DSH did not retain a portable historical snapshot')
  await fail('cloud_restore_version', { remote_path: versionPath, version_id: '../escape' }, /opaque identifier/)
  await fail('cloud_restore_version', { remote_path: versionPath, version_id: '999999999999999999' }, /VERSION_NOT_FOUND/)
  const oldest = versions.versions.filter(item => item.source === 'managed').at(-1)
  await call('cloud_restore_version', { remote_path: versionPath, version_id: oldest.versionId })
  const historical = await call('cloud_download', { remote_path: versionPath, output: 'text' })
  assert.equal(historical.content, `version-one-${stamp}`)
} finally {
  const rootStat = await execute('cloud_stat', { remote_path: root })
  if (!rootStat.isError) await call('cloud_delete', { remote_path: root })
  await call('cloud_logout')
}

process.stdout.write(`PHASE3_DSH_DISPATCH_OK ${username}\n`)
