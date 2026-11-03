import assert from 'node:assert/strict'
import test from 'node:test'
import {
  discoverCloudShares,
  emptyAgentState,
  ensureCloudWatch,
  observeCloudEtag,
} from '../dist/domain.js'

test('the first Cloud observation establishes a baseline without waking the Agent', () => {
  const state = emptyAgentState()
  const additions = discoverCloudShares(state, [{ shareId: '1', path: '/old.txt' }], '2026-10-01T00:00:00.000Z', 100)
  assert.deepEqual(additions, [])
  assert.equal(state.cloudBaselineEstablished, true)
  assert.deepEqual(state.seenCloudShareIds, ['1'])
})

test('a later incoming share becomes one durable attention item and is deduplicated', () => {
  const state = emptyAgentState()
  discoverCloudShares(state, [], '2026-10-01T00:00:00.000Z', 100)
  const additions = discoverCloudShares(state, [{ shareId: '7', targetPath: '/new.txt', ownerId: 'bob' }], '2026-10-01T00:01:00.000Z', 100)
  assert.equal(additions.length, 1)
  assert.equal(additions[0].id, 'cloud-share:7')
  assert.equal(additions[0].summary, 'bob shared /new.txt')
  assert.equal(discoverCloudShares(state, [{ shareId: '7', path: '/new.txt' }], '2026-10-01T00:02:00.000Z', 100).length, 0)
  assert.equal(state.attention.length, 1)
})

test('a watched file establishes an ETag baseline and emits one event per later ETag', () => {
  const state = emptyAgentState()
  const watch = ensureCloudWatch(state, { shareId: '8', direction: 'incoming', targetPath: '/chat.md' })
  assert.ok(watch)
  assert.equal(observeCloudEtag(state, watch, 'etag-1', '2026-10-01T00:00:00.000Z'), undefined)
  const changed = observeCloudEtag(state, watch, 'etag-2', '2026-10-01T00:01:00.000Z')
  assert.equal(changed.id, 'cloud-file-change:8:etag-2')
  assert.equal(observeCloudEtag(state, watch, 'etag-2', '2026-10-01T00:02:00.000Z'), undefined)
})

test('Agent state stores only the Schedule task identity for a heartbeat', () => {
  const state = emptyAgentState()
  state.heartbeatScheduleId = 'schedule-heartbeat-1'
  assert.equal(state.heartbeatScheduleId, 'schedule-heartbeat-1')
  assert.equal(Object.hasOwn(state, 'heartbeat'), false)
})
