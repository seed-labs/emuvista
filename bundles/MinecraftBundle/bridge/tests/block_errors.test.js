'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { createToolApi } = require('../tool_api')

test('block search reports both invalid limits before searching, and preserves valid requests', () => {
  const calls = []
  const bot = {
    registry: { blocksByName: { oak_log: { id: 49 } } },
    findBlocks: args => { calls.push(args); return [] }
  }
  const dispatch = createToolApi({ bot }, { ready () {} })
  assert.throws(() => dispatch('GET', '/blocks', { name: 'oak_log', radius: 64, count: 50 }),
    /radius=64.*1 to 32.*count=50.*1 to 20.*move/)
  assert.throws(() => dispatch('GET', '/blocks', { name: 'log' }), /unknown block name "log".*oak_log/)
  assert.equal(calls.length, 0)
  assert.deepEqual(dispatch('GET', '/blocks', { name: 'oak_log', radius: 32, count: 20 }).blocks, [])
  assert.deepEqual(calls[0], { matching: 49, maxDistance: 32, count: 20 })
  dispatch('GET', '/blocks', { name: 'oak_log' })
  assert.equal(calls[1].maxDistance, 16)
  assert.equal(calls[1].count, 10)
})

test('inspect identifies invalid coordinate fields', () => {
  const dispatch = createToolApi({ bot: {} }, { ready () {} })
  assert.throws(() => dispatch('GET', '/block', { x: 0.5, y: 2 }), /invalid coordinates x, z.*safe integers/)
})
