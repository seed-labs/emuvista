import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as CloudPlugin from '../dist/client.js'

const serverUrl = process.env.DSH_TEST_SERVER_URL ?? 'https://cloud.seedvista.test'
const alicePassword = process.env.DSH_TEST_ALICE_PASSWORD
const bobPassword = process.env.DSH_TEST_BOB_PASSWORD
assert.ok(alicePassword, 'DSH_TEST_ALICE_PASSWORD is required')
assert.ok(bobPassword, 'DSH_TEST_BOB_PASSWORD is required')

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CloudPlugin, { maxInlineBytes: 65536, maxTransferBytes: 8 * 1024 * 1024 })

const agents = {
  alice: { id: 'meeting-alice' },
  bob: { id: 'meeting-bob' },
}
const signal = new AbortController().signal
let sequence = 0

async function call(agentName, name, args = {}) {
  const result = await ctx.tools.execute({
    signal,
    callId: ToolCallId(`meeting-${agentName}-${++sequence}`),
    name,
    arguments: args,
    agent: agents[agentName],
  })
  if (result.isError) throw new Error(`${agentName}:${name}: ${result.error.message}`)
  return result.value
}

function sha256(text) {
  return createHash('sha256').update(text).digest('hex')
}

await call('alice', 'cloud_login', { server_url: serverUrl, username: 'alice', password: alicePassword })
await call('bob', 'cloud_login', { server_url: serverUrl, username: 'bob', password: bobPassword })

const stamp = `${Date.now()}-${process.pid}`
const transfers = [
  { sender: 'alice', recipient: 'bob', content: `meeting ${stamp}: alice to bob` },
  { sender: 'bob', recipient: 'alice', content: `meeting ${stamp}: bob to alice` },
]
const cleanup = []

try {
  for (const transfer of transfers) {
    const root = `/dsh-meeting-${stamp}-${transfer.sender}`
    const remotePath = `${root}/message.txt`
    await call(transfer.sender, 'cloud_upload', {
      remote_path: remotePath,
      content: transfer.content,
      create_parents: true,
    })
    const shared = await call(transfer.sender, 'cloud_share', {
      remote_path: remotePath,
      recipient: transfer.recipient,
      share_type: 'user',
      permissions: ['read'],
      note: `dsh-meeting-${stamp}`,
    })
    cleanup.push({ owner: transfer.sender, shareId: shared.shareId, root })

    const incoming = await call(transfer.recipient, 'cloud_list_shares', {
      direction: 'incoming',
      limit: 100,
    })
    const found = incoming.shares.find((item) => item.shareId === shared.shareId)
    assert.ok(found?.targetPath, `${transfer.recipient} did not discover share ${shared.shareId}`)
    const downloaded = await call(transfer.recipient, 'cloud_download', {
      remote_path: found.targetPath,
      output: 'text',
    })
    assert.equal(downloaded.content, transfer.content)
    process.stdout.write(
      `PASS ${transfer.sender}->${transfer.recipient} share=${shared.shareId} sha256=${sha256(downloaded.content)}\n`,
    )
  }
} finally {
  for (const item of cleanup.reverse()) {
    await call(item.owner, 'cloud_unshare', { share_id: item.shareId })
    await call(item.owner, 'cloud_delete', { remote_path: item.root })
  }
  await call('alice', 'cloud_logout')
  await call('bob', 'cloud_logout')
}

process.stdout.write('BIDIRECTIONAL_CLOUD_EXCHANGE_OK\n')
