import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { applyEvent, emotionAt } from '../dist/emotion.js'
import Soul from '../dist/index.js'
import { SoulStore } from '../dist/store.js'

test('evidence-backed intentions persist across sessions and own a single reminder', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'emuvista-soul-'))
  try {
    const path = join(directory, 'state.json')
    const tasks = new Map()
    let context
    const schedule = {
      list: async ({ sessionId }) => [...tasks.values()].filter(task => task.sessionId === sessionId),
      create: async (sessionId, args) => {
        assert.equal(args.after_seconds ?? args.every_seconds, 90)
        const task = { ...args, sessionId, id: args.title, scheduledAt: Date.now() + 90000 }
        tasks.set(task.id, task)
        return task
      },
      delete: async ({ sessionId, id }) => {
        assert.equal(tasks.get(id)?.sessionId, sessionId)
        assert(tasks.delete(id))
      },
    }
    const mount = async (id) => {
      const store = new SoulStore(path, 'bob')
      await store.ready
      const tools = new Map()
      const agent = { id, ctx: {
        tools: { register: tool => { tools.set(tool.name, tool); return () => tools.delete(tool.name) } },
        systemPrompt: { context: entry => { context = entry; return () => {} } },
      } }
      const host = { ctx: { schedule }, store, persona: 'Bob', emotion: Soul.prototype.emotion, clearSchedule: Soul.prototype.clearSchedule }
      const dispose = Soul.prototype.register.call(host, agent)
      return { dispose, call: (name, args) => tools.get(name).execute(args, {}) }
    }
    const first = await mount('session-first')
    const experience = await first.call('soul_remember', {
      kind: 'experience', text: 'Read the draft', certainty: 'observed', source: 'tool:41',
    })
    assert.deepEqual(JSON.parse(JSON.stringify(experience)), experience)
    const memory = await first.call('soul_remember', {
      kind: 'relationship', text: 'Promised to check the final version', about: 'Alice',
      certainty: 'observed', source: 'message:42',
    })
    await assert.rejects(first.call('soul_reflect', { judgment: 'guess', evidence_ids: 'missing' }), /evidence ID/)
    const { wish } = await first.call('soul_reflect', {
      judgment: 'I owe Alice a review', evidence_ids: memory.id, wish: 'Review the final draft',
    })
    const rest = { intention_id: wish.id, after_seconds: 90, question: 'Has Alice confirmed the final draft?' }
    await assert.rejects(first.call('soul_rest', rest), /active intention/)
    await first.call('soul_intention_update', {
      id: wish.id, status: 'active', reason: 'Keep my promise', completion: 'Confirm version and verify content',
    })
    await first.call('soul_rest', rest)
    assert.equal(tasks.size, 1)
    const life = await first.call('soul_life', { enabled: true, interval_seconds: 90 })
    assert.equal((await first.call('soul_life', { enabled: true })).scheduleId, life.scheduleId)
    assert.equal(tasks.size, 2)
    first.dispose()

    const second = await mount('session-second')
    const recalled = await second.call('soul_recall', { query: 'Alice' })
    assert(recalled.entries.some(entry => entry.id === memory.id))
    assert.equal(recalled.intentions[0].id, wish.id)
    assert.match(context.text(), /Review the final draft/)
    await assert.rejects(second.call('soul_life', { enabled: true }), /Another session owns/)
    await second.call('soul_life', { enabled: false })
    assert.equal(tasks.size, 0)
    await second.call('soul_rest', rest)
    assert.deepEqual([...tasks.values()].map(task => task.sessionId), ['session-second'])
    await second.call('soul_intention_update', { id: wish.id, status: 'completed', reason: 'Verified final draft' })
    assert.equal(tasks.size, 0)
    const recalledAll = await second.call('soul_recall', {})
    assert.deepEqual(recalledAll.intentions, [])
    assert.deepEqual(JSON.parse(JSON.stringify(recalledAll)), recalledAll)
    second.dispose()

    await assert.rejects(new SoulStore(path, 'alice').ready, /configured resident/)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('automatic reflection saves a visible, evidence-backed concern without adopting or scheduling it', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'emuvista-soul-reflection-'))
  try {
    const path = join(directory, 'state.json')
    const store = new SoulStore(path, 'resident')
    await store.ready
    let context
    let calls = 0
    let answer
    let reflectionInput
    const tools = new Map()
    const agent = {
      id: 'session-first',
      session: { id: 'session-first', requestHeader: () => ({ config: { provider: 'test', model: 'test-model' } }) },
      ctx: {
        tools: { register: tool => { tools.set(tool.name, tool); return () => tools.delete(tool.name) } },
        systemPrompt: { context: entry => { context = entry; return () => {} } },
      },
    }
    const host = {
      store,
      emotion: Soul.prototype.emotion,
      persona: JSON.stringify({ identity: 'A curious resident' }),
      lifetime: new AbortController(),
      ctx: {
        logger: { warn: () => {} },
        llm: { stream: async function* (request) {
          calls++
          assert.equal(request.model, 'test-model')
          assert.equal(request.tools, undefined)
          reflectionInput = JSON.parse(request.messages[0].content[0].text)
          const value = JSON.stringify(answer)
          yield { type: 'block-start', index: 0, blockType: 'text' }
          yield { type: 'text-delta', index: 0, text: value }
          yield { type: 'block-end', index: 0, block: { type: 'text', text: value } }
          yield { type: 'finish', reason: { kind: 'stop' } }
        } },
      },
    }
    const dispose = Soul.prototype.register.call(host, agent)
    const remember = source => tools.get('soul_remember').execute({
      kind: 'experience', certainty: 'observed', text: 'Read a draft', source,
    })
    const reflect = () => Soul.prototype.reflectAutomatically.call(host, agent)
    const first = await remember('message:1')
    await remember('message:2')
    await reflect()
    assert.equal(calls, 0)
    const last = await remember('message:3')
    answer = [
      { action: 'create', wish: 'Check the source list', judgment: 'The draft needs references', evidenceIds: [first.id], weight: 0 },
      { action: 'create', wish: 'Ask about the deadline', judgment: 'The schedule is unclear', evidenceIds: ['missing'], weight: 100 },
    ]
    await reflect()
    assert.equal(store.snapshot().lastAutoReflectionMemoryId, undefined)
    assert.deepEqual(store.snapshot().intentions, [])
    answer[1].evidenceIds = [last.id]
    answer[1].weight = 101
    await reflect()
    assert.deepEqual(store.snapshot().intentions, [])
    answer[1].weight = 100
    answer.push({ ...answer[0], wish: 'check the   source list' })
    for (let i = 1; i <= 4; i++) {
      answer.push({ ...answer[0], wish: 'Additional wish ' + i, weight: i * 10 })
    }
    await Promise.all([reflect(), reflect()])
    assert.equal(calls, 3)
    const state = store.snapshot()
    assert.equal(state.lastAutoReflectionMemoryId, last.id)
    assert.deepEqual(state.entries.find(entry => entry.id === state.intentions[1].reflectionId).evidence, [last.id])
    assert.deepEqual(state.intentions.map(item => item.weight), [0, 100, 10, 20, 30, 40])
    assert.equal(state.intentions[0].status, 'candidate')
    assert.equal(state.rest, undefined)
    assert.match(context.text(), /Current concerns.*Ask about the deadline.*Check the source list/)
    const injected = JSON.parse(context.text().split('\n').find(line => line.startsWith('Current concerns:') || line.startsWith('Current concerns (')).split(': ', 2)[1])
    assert.deepEqual(injected.map(item => item.weight), [100, 40, 30, 20, 10, 0])
    assert.match(context.text(), /Current intentions: \[\]/)
    await reflect()
    assert.equal(calls, 3)
    await remember('message:4')
    await remember('message:5')
    const fourth = await remember('message:6')
    answer = []
    await reflect()
    assert.equal(calls, 4)
    const restored = new SoulStore(path, 'resident')
    await restored.ready
    assert.equal(restored.snapshot().lastAutoReflectionMemoryId, fourth.id)
    assert.equal(restored.snapshot().intentions.length, 6)
    const original = state.intentions[0]
    assert.deepEqual(restored.snapshot().intentions[0], original)
    const addEvidence = async label => {
      await remember(label + ':1')
      await remember(label + ':2')
      return remember(label + ':3')
    }
    const source = await addEvidence('new citation')
    const revision = {
      action: 'update', id: original.id, wish: 'Verify the draft references', weight: 70,
      judgment: 'New references warrant a closer review', evidenceIds: [source.id],
    }
    answer = [revision, { ...revision }]
    await reflect()
    assert.deepEqual(store.snapshot().intentions[0], original)
    assert.equal(store.snapshot().lastAutoReflectionMemoryId, fourth.id)
    answer = [{ ...revision, id: 'unknown-concern' }]
    await reflect()
    assert.deepEqual(store.snapshot().intentions[0], original)
    answer = [revision]
    await reflect()
    assert(reflectionInput.existingConcerns.some(item => item.id === original.id && item.weight === 0))
    const updated = store.snapshot().intentions[0]
    assert.equal(updated.id, original.id)
    assert.equal(updated.reflectionId, original.reflectionId)
    assert.equal(updated.reason, revision.judgment)
    const updateRecord = store.snapshot().entries.find(entry => entry.id === updated.latestReflectionId)
    assert.deepEqual(updateRecord.evidence, [source.id])
    assert.deepEqual(updateRecord.concernRevision, {
      intentionId: original.id, action: 'update',
      before: { wish: original.wish, weight: 0, shelved: false },
      after: { wish: revision.wish, weight: 70, shelved: false },
    })
    assert.deepEqual(store.snapshot().intentions[1], state.intentions[1])

    const archived = await addEvidence('publication postponed')
    answer = [{ action: 'shelve', id: original.id, judgment: 'Publication was postponed', evidenceIds: [archived.id] }]
    await reflect()
    assert.equal(store.snapshot().intentions[0].shelved, true)
    assert.doesNotMatch(context.text(), /Verify the draft references/)
    const published = await addEvidence('publication announced')
    answer = [{ action: 'restore', id: original.id, judgment: 'Publication resumed', evidenceIds: [published.id] }]
    await reflect()
    assert(reflectionInput.existingConcerns.some(item => item.id === original.id && item.shelved))
    assert.match(context.text(), /Verify the draft references/)
    const afterRestart = new SoulStore(path, 'resident')
    await afterRestart.ready
    const saved = afterRestart.snapshot()
    assert.equal(saved.intentions.length, 6)
    assert.equal(saved.intentions[0].id, original.id)
    assert.equal(saved.intentions[0].weight, 70)
    assert.deepEqual(saved.entries.filter(entry => entry.concernRevision?.intentionId === original.id)
      .map(entry => entry.concernRevision.action), ['update', 'shelve', 'restore'])
    host.concernIntervalMs = 5000
    host.nextTimedAttemptAt = 0
    await store.run(async () => {
      const persisted = store.snapshot()
      for (const item of persisted.intentions) item.shelved = item.id !== original.id
      persisted.intentions[0].updatedAt = new Date(Date.now() - 6000).toISOString()
      await store.save(persisted)
    })
    answer = []
    const cursor = store.snapshot().lastAutoReflectionMemoryId
    const countBefore = calls
    await Soul.prototype.reflectAutomatically.call(host, agent, true)
    assert.equal(calls, countBefore + 1)
    assert.equal(reflectionInput.focusConcernId, original.id)
    assert(reflectionInput.memories.length > 0)
    assert.equal(store.snapshot().lastAutoReflectionMemoryId, cursor)
    assert(store.snapshot().concernReviews[original.id].firstAt > 0)
    await Soul.prototype.reflectAutomatically.call(host, agent, true)
    assert.equal(calls, countBefore + 1)
    assert.equal(saved.rest, undefined)
    dispose()
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('emotion appraisals decay toward the resident baseline and apply once per event', async () => {
  const baseline = { worry: 10, frustration: 20, joy: 30 }
  const start = applyEvent(baseline, { worry: 100, frustration: 30, joy: -50 }, 5000)
  assert.deepEqual(start.vector, { worry: 100, frustration: 50, joy: 0 })
  assert.deepEqual(emotionAt(start, baseline, 1000, 6000), { worry: 55, frustration: 35, joy: 15 })
  assert.deepEqual(emotionAt(start, baseline, 1000, 4000), start.vector)
  const directory = await mkdtemp(join(tmpdir(), 'emuvista-soul-emotion-'))
  try {
    const path = join(directory, 'state.json')
    const store = new SoulStore(path, 'resident')
    await store.ready
    const tools = new Map()
    const ctx = {
      tools: { register: tool => { tools.set(tool.name, tool); return () => tools.delete(tool.name) } },
      systemPrompt: { context: () => () => {} },
    }
    const host = { store, emotionConfig: { baseline, halfLifeMs: 1000 }, emotion: Soul.prototype.emotion }
    const dispose = Soul.prototype.register.call(host, { id: 'session', ctx })
    const remember = tools.get('soul_remember').execute
    const appraise = tools.get('soul_appraise').execute
    await assert.rejects(appraise({ event_id: 'missing', worry: 20, frustration: 0, joy: 0 }), /saved experience/)
    const entry = await remember({ kind: 'experience', certainty: 'observed', text: 'A delay was announced', source: 'message:1' })
    const args = { event_id: entry.id, worry: 20, frustration: 0, joy: 0 }
    await assert.rejects(appraise({ ...args, worry: 101 }), /emotion change/)
    assert.equal((await appraise(args)).emotion.worry, 30)
    assert.equal((await appraise(args)).alreadyAppraised, true)
    const restored = new SoulStore(path, 'resident')
    await restored.ready
    assert.deepEqual(restored.snapshot().affect.vector, { worry: 30, frustration: 20, joy: 30 })
    dispose()
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
