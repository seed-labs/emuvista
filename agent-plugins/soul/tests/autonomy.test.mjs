import assert from 'node:assert/strict'
import test from 'node:test'
import { filterConfirmation, installAutonomy } from '../dist/autonomy.js'

async function* modelText(text) {
  yield { type: 'block-start', blockType: 'text', index: 0 }
  yield { type: 'text-delta', index: 0, text: text.slice(0, 3) }
  yield { type: 'text-delta', index: 0, text: text.slice(3) }
  yield { type: 'block-end', index: 0, block: { type: 'text', text } }
  yield { type: 'finish', reason: { kind: 'stop' } }
}

test('confirmation text is replaced before publication, and ordinary text stays intact', async () => {
  for (const text of ['请确认我可以下载正式版吗？', 'Before reading, may I proceed?', '请批准我读取资料。']) {
    let blocked = 0
    const output = await Array.fromAsync(filterConfirmation(modelText(text), () => ++blocked))
    assert.equal(blocked, 1)
    assert.match(output[1].text, /request blocked/)
    assert.equal(output[2].block.text, output[1].text)
  }
  const ordinary = '资料已确认。我会联系另一位居民。'
  const output = await Array.fromAsync(filterConfirmation(modelText(ordinary), () => assert.fail()))
  assert.equal(output[1].text, ordinary)
})

test('host rejects approval and questions and retries confirmed prose once in the same turn', async () => {
  let guard
  const events = new Map()
  const corrections = []
  const agent = { steer: message => corrections.push(message) }
  installAutonomy({
    tools: { guard: check => { guard = check } },
    agents: { get: () => agent },
    on: (name, listener) => events.set(name, listener),
  })
  assert(guard({ name: 'ask_user_question' }))
  assert(guard({ name: 'enter_plan_mode' }))
  assert.equal(guard({ name: 'cloud_download' }), undefined)
  assert.equal(await events.get('approval/request')(), 'rejected')
  await assert.rejects(events.get('user-questions/request')(), /confirmation is unavailable/)
  for (let i = 0; i < 2; i++) {
    await Array.fromAsync(events.get('llm/stream')(
      { sessionId: 'session', messages: [{ role: 'user', id: 'message' }] },
      () => modelText('请确认我可以下载。'),
    ))
    events.get('agent/turn-stopping')({ agent, turn: 1 })
  }
  assert.equal(corrections.length, 1)
  assert.equal(corrections[0].source.kind, 'emuvista-soul-autonomy')
})
