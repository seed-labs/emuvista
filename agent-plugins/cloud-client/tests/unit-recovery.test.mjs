import assert from 'node:assert/strict'
import test from 'node:test'
import { createRecoveryTools } from '../dist/client.js'

test('third batch exposes every planned recovery tool exactly once', () => {
  const names = createRecoveryTools().map(tool => tool.name)
  assert.deepEqual(names, [
    'cloud_list_trash', 'cloud_restore_trash', 'cloud_delete_permanently',
    'cloud_list_versions', 'cloud_restore_version',
  ])
  assert.equal(new Set(names).size, names.length)
})

test('recovery tools require an Agent login', async () => {
  const listTrash = createRecoveryTools().find(tool => tool.name === 'cloud_list_trash')
  await assert.rejects(
    listTrash.execute({}, { agent: {}, signal: new AbortController().signal }),
    /NOT_LOGGED_IN/,
  )
})
