import assert from 'node:assert/strict'
import test from 'node:test'
import Claw from '../dist/index.js'
import { emptyAgentState } from '../dist/domain.js'

test('world check reports the established baseline on the first call and subsequent calls', async () => {
  const state = emptyAgentState()
  const observer = {
    serialize: action => action(),
    callTool: async () => ({ value: { shares: [] } }),
    stateFor: () => state,
    maxSeenCloudShares: 100,
    save: async () => {},
    deliverCloudEvents: async () => assert.fail('an empty baseline must not wake the Agent'),
  }
  const agent = { id: 'baseline-contract' }
  const first = await Claw.prototype.observeCloud.call(observer, agent)
  assert.deepEqual(first, { baseline: true, baselineCreated: true, additions: 0 })
  const next = await Claw.prototype.observeCloud.call(observer, agent)
  assert.deepEqual(next, { baseline: true, baselineCreated: false, additions: 0 })
})
