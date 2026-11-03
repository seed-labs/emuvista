// One real ToolRuntime in the calling container. Credentials arrive via stdin.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
const require = createRequire('/opt/emuvista/agent-plugins/cloud-client/package.json')
const load = (name) => import(pathToFileURL(require.resolve(name)).href)
const [{ Context }, { ToolCallId }, { default: SystemPrompt }, { default: ToolRuntime }, Cloud] =
  await Promise.all([
    load('@deepseek-ai/cordis'), load('@deepseek-ai/dsh-llm'),
    load('@deepseek-ai/dsh-system-prompt'), load('@deepseek-ai/dsh-tools'),
    import('/opt/emuvista/agent-plugins/cloud-client/dist/client.js'),
  ])
let input = ''
for await (const chunk of process.stdin) input += chunk
const args = JSON.parse(input)
const ctx = new Context()
const fibers = []
async function mount(plugin, config) {
  const fiber = ctx.plugin(plugin, config)
  fibers.push(fiber)
  await fiber
}
await mount(SystemPrompt, {})
await mount(ToolRuntime)
await mount(Cloud, {})
const agent = { id: 'h14-worker-' + args.username }
let sequence = 0
const signal = new AbortController().signal
async function call(name, arguments_ = {}) {
  const result = await ctx.tools.execute({
    signal, callId: ToolCallId('h14-' + ++sequence), name,
    arguments: arguments_, agent,
  })
  if (result.isError) throw new Error(name + ': ' + result.error.message)
  return result.value
}
let output
try {
  if (args.action === 'inventory') {
    const schemas = ctx.tools.schemas()
    assert.equal(schemas.length, 23)
    const unauthenticated = await ctx.tools.execute({
      signal, callId: ToolCallId('no-login'), name: 'cloud_account', arguments: {}, agent,
    })
    assert.equal(unauthenticated.isError, true)
    output = { count: schemas.length, tools: schemas.map(item => item.name) }
  } else {
    await call('cloud_login', {
      server_url: 'https://cloud.seedvista.test',
      username: args.username, password: args.password,
    })
    if (args.action === 'send') {
      await call('cloud_upload', { remote_path: args.remote, content: args.content, create_parents: true })
      output = await call('cloud_share', {
        remote_path: args.remote, recipient: args.recipient,
        share_type: 'user', permissions: ['read'],
      })
    } else if (args.action === 'receive') {
      const incoming = await call('cloud_list_shares', { direction: 'incoming', limit: 100 })
      const share = incoming.shares.find(item => String(item.shareId) === String(args.share_id))
      assert.ok(share?.targetPath, 'Incoming share not found')
      const downloaded = await call('cloud_download', { remote_path: share.targetPath, output: 'text' })
      output = { sha256: createHash('sha256').update(downloaded.content).digest('hex') }
    } else if (args.action === 'cleanup') {
      if (args.share_id) await call('cloud_unshare', { share_id: args.share_id })
      await call('cloud_delete', { remote_path: args.remote.slice(0, args.remote.lastIndexOf('/')) })
      output = { cleaned: true }
    } else {
      throw new Error('Unknown worker action')
    }
    await call('cloud_logout')
  }
  process.stdout.write(JSON.stringify(output) + '\n')
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose()
}
