import assert from 'node:assert/strict'
import test from 'node:test'
import { buildSearchBody, createExtendedTools, mapRecipients } from '../dist/client.js'

test('second batch exposes every planned extended tool exactly once', () => {
  const names = createExtendedTools().map(tool => tool.name)
  assert.deepEqual(names, ['cloud_copy', 'cloud_search', 'cloud_get_share', 'cloud_search_recipients'])
  assert.equal(new Set(names).size, names.length)
})

test('search body escapes user text and scopes to the authenticated account', () => {
  const xml = buildSearchBody(
    { username: 'alice & admin' },
    '/A folder',
    '<needle & value>',
    17,
  ).toString('utf8')
  assert.match(xml, /\/files\/alice%20%26%20admin\/A%20folder/)
  assert.match(xml, /%&lt;needle &amp; value&gt;%/)
  assert.match(xml, /<d:nresults>17<\/d:nresults>/)
  assert.doesNotMatch(xml, /<needle/)
})

test('recipient mapping merges exact and suggested results without duplicates', () => {
  const recipients = mapRecipients({
    exact: { users: [{ label: 'Alice', value: { shareType: 0, shareWith: 'alice' } }] },
    users: [
      { label: 'Alice duplicate', value: { shareType: 0, shareWith: 'alice' } },
      { label: 'Bob', value: { shareType: 0, shareWith: 'bob' } },
    ],
    groups: [{ label: 'Team', value: { shareType: 1, shareWith: 'team' } }],
  })
  assert.deepEqual(recipients, [
    { recipient: 'alice', displayName: 'Alice', shareType: '0', category: 'users', exact: true },
    { recipient: 'bob', displayName: 'Bob', shareType: '0', category: 'users', exact: false },
    { recipient: 'team', displayName: 'Team', shareType: '1', category: 'groups', exact: false },
  ])
})

test('extended tools reject use before an Agent login', async () => {
  const copy = createExtendedTools().find(tool => tool.name === 'cloud_copy')
  await assert.rejects(
    copy.execute({ source_path: '/a', destination_path: '/b' }, { agent: {}, signal: new AbortController().signal }),
    /NOT_LOGGED_IN/,
  )
})
