import assert from 'node:assert/strict'
import test from 'node:test'
import { createCoreTools } from '../dist/client.js'
import {
  CloudDriveError,
  maskToPermissions,
  normalizeBaseUrl,
  normalizeRemotePath,
  parseDavResponses,
  permissionsToMask,
} from '../dist/client.js'

const signal = new AbortController().signal

test('first batch exposes every planned core tool exactly once', () => {
  const names = createCoreTools().map(tool => tool.name)
  assert.deepEqual(names, [
    'cloud_login', 'cloud_logout', 'cloud_account', 'cloud_list', 'cloud_stat',
    'cloud_mkdir', 'cloud_upload', 'cloud_download', 'cloud_move', 'cloud_delete',
    'cloud_share', 'cloud_list_shares', 'cloud_update_share', 'cloud_unshare',
  ])
  assert.equal(new Set(names).size, names.length)
})

test('remote paths admit root only when requested and reject traversal forms', () => {
  assert.equal(normalizeRemotePath('/', { allowRoot: true }), '/')
  assert.equal(normalizeRemotePath('//Folder/a b.txt'), '/Folder/a b.txt')
  for (const candidate of ['/', '/../escape', '/a/./b', '/a\\b', '/\0bad']) {
    assert.throws(() => normalizeRemotePath(candidate), CloudDriveError)
  }
})

test('base URLs reject credentials, queries, fragments, and non-http schemes', () => {
  assert.equal(normalizeBaseUrl('https://cloud.example.test/base/'), 'https://cloud.example.test/base')
  for (const candidate of [
    'ftp://cloud.example.test',
    'https://user:pass@cloud.example.test',
    'https://cloud.example.test?q=1',
    'https://cloud.example.test/#fragment',
  ]) assert.throws(() => normalizeBaseUrl(candidate), CloudDriveError)
})

test('semantic permissions round-trip and reject empty or unknown values', () => {
  assert.equal(permissionsToMask(['read', 'update', 'read']), 3)
  assert.deepEqual(maskToPermissions(31), ['read', 'update', 'create', 'delete', 'share'])
  assert.throws(() => permissionsToMask([]), /INVALID_PERMISSIONS/)
  assert.throws(() => permissionsToMask(['admin']), /unknown permission/)
})

test('WebDAV XML parsing extracts files without evaluating entities', () => {
  const account = { baseUrl: 'https://cloud.example.test', username: 'alice' }
  const xml = Buffer.from(`<?xml version="1.0"?>
  <d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
    <d:response><d:href>/remote.php/dav/files/alice/Folder/a%20b.txt</d:href>
      <d:propstat><d:prop><d:displayname>a b.txt</d:displayname><d:getcontentlength>5</d:getcontentlength>
      <d:getetag>&quot;etag&quot;</d:getetag><oc:fileid>42</oc:fileid><d:resourcetype/></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
  </d:multistatus>`)
  const [entry] = parseDavResponses(account, xml)
  assert.equal(entry.remotePath, '/Folder/a b.txt')
  assert.equal(entry.size, 5)
  assert.equal(entry.fileId, '42')
  assert.equal(entry.etag, '"etag"')

  const unsafe = Buffer.from('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><d:multistatus xmlns:d="DAV:"/>')
  assert.throws(() => parseDavResponses(account, unsafe), /DOCTYPE/)
})

test('tools require an Agent login and logout is idempotent', async () => {
  const tools = new Map(createCoreTools().map(tool => [tool.name, tool]))
  const exec = { agent: {}, signal }
  await assert.rejects(
    tools.get('cloud_list').execute({ remote_path: '/' }, exec),
    /NOT_LOGGED_IN/,
  )
  assert.deepEqual(await tools.get('cloud_logout').execute({}, exec), { loggedOut: false, username: null })
})
