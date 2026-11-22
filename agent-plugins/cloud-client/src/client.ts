import { spawn } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import { basename, dirname, join } from 'node:path'
import { homedir, tmpdir } from 'node:os'
import { SaxesParser } from 'saxes'
import { defineTool } from '@deepseek-ai/dsh-tools'

const DEFAULT_TIMEOUT_MS = 60_000
const DEFAULT_MAX_TRANSFER_BYTES = 8 * 1024 * 1024
const DEFAULT_MAX_INLINE_BYTES = 64 * 1024
const DEFAULT_MAX_METADATA_BYTES = 2 * 1024 * 1024
const MAX_ERROR_BYTES = 64 * 1024
const accounts = new WeakMap()

export class CloudDriveError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(`${code}: ${message}`)
    this.name = 'CloudDriveError'
    this.code = code
    this.details = details
  }
}

export function requiredText(value, name) {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new CloudDriveError('INVALID_ARGUMENT', `${name} must be a non-empty string`)
  }
  return value.trim()
}

export function optionalText(value, name) {
  if (value === undefined || value === null) return undefined
  return requiredText(value, name)
}

export function positiveInteger(value, fallback, name, maximum = Number.MAX_SAFE_INTEGER) {
  if (value === undefined) return fallback
  if (!Number.isSafeInteger(value) || value <= 0 || value > maximum) {
    throw new CloudDriveError('INVALID_ARGUMENT', `${name} must be an integer from 1 through ${maximum}`)
  }
  return value
}

export function runtimeConfig(config: Record<string, any> = {}) {
  config ??= {}
  return {
    curlPath: typeof config.curlPath === 'string' && config.curlPath !== '' ? config.curlPath : '/usr/bin/curl',
    timeoutMs: positiveInteger(config.timeoutMs, DEFAULT_TIMEOUT_MS, 'timeoutMs', 30 * 60_000),
    maxTransferBytes: positiveInteger(config.maxTransferBytes, DEFAULT_MAX_TRANSFER_BYTES, 'maxTransferBytes', 1024 * 1024 * 1024),
    maxInlineBytes: positiveInteger(config.maxInlineBytes, DEFAULT_MAX_INLINE_BYTES, 'maxInlineBytes', 4 * 1024 * 1024),
    maxMetadataBytes: positiveInteger(config.maxMetadataBytes, DEFAULT_MAX_METADATA_BYTES, 'maxMetadataBytes', 64 * 1024 * 1024),
    downloadDirectory: typeof config.downloadDirectory === 'string' && config.downloadDirectory !== ''
      ? config.downloadDirectory
      : process.env.DSH_CLOUD_DOWNLOAD_DIR ?? '/tmp/dsh-cloud-downloads',
    versionDirectory: typeof config.versionDirectory === 'string' && config.versionDirectory !== ''
      ? config.versionDirectory
      : process.env.DSH_CLOUD_VERSION_DIR ?? join(homedir(), '.dsh', 'storages', 'emuvista-cloud-versions'),
    baseUrl: config.baseUrl ?? process.env.DSH_CLOUD_BASE_URL,
    username: config.username ?? process.env.DSH_CLOUD_USERNAME,
  }
}

export function normalizeBaseUrl(value) {
  let url
  try { url = new URL(requiredText(value, 'server_url')) } catch (error) {
    throw new CloudDriveError('INVALID_SERVER_URL', `server_url is not a valid URL: ${error.message}`)
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new CloudDriveError('INVALID_SERVER_URL', 'server_url must use http or https')
  }
  if (url.username !== '' || url.password !== '' || url.search !== '' || url.hash !== '') {
    throw new CloudDriveError('INVALID_SERVER_URL', 'server_url must not contain credentials, a query, or a fragment')
  }
  url.pathname = `${url.pathname.replace(/\/+$/, '')}/`
  return url.toString().replace(/\/$/, '')
}

export function normalizeRemotePath(value, { allowRoot = false, name = 'remote_path' } = {}) {
  const input = requiredText(value, name)
  if (input.includes('\0') || input.includes('\\')) {
    throw new CloudDriveError('INVALID_PATH', `${name} must not contain NUL or backslashes`)
  }
  const segments = input.split('/').filter(Boolean)
  if (segments.some(segment => segment === '.' || segment === '..')) {
    throw new CloudDriveError('INVALID_PATH', `${name} must not contain dot segments`)
  }
  if (segments.length === 0) {
    if (allowRoot) return '/'
    throw new CloudDriveError('INVALID_PATH', `${name} must identify a non-root item`)
  }
  return `/${segments.join('/')}`
}

export function encodeRemotePath(path) {
  return path.split('/').filter(Boolean).map(encodeURIComponent).join('/')
}

export function endpoint(account, path) {
  return new URL(path, `${account.baseUrl}/`).toString()
}

export function davUrl(account, remotePath = '/') {
  const suffix = remotePath === '/' ? '' : encodeRemotePath(remotePath)
  return endpoint(account, `remote.php/dav/files/${encodeURIComponent(account.username)}/${suffix}`)
}

export function davRootUrl(account) {
  return endpoint(account, 'remote.php/dav/')
}

export function trashItemUrl(account, itemId) {
  return endpoint(account, `remote.php/dav/trashbin/${encodeURIComponent(account.username)}/trash/${encodeURIComponent(itemId)}`)
}

export function trashRootUrl(account) {
  return endpoint(account, `remote.php/dav/trashbin/${encodeURIComponent(account.username)}/trash`)
}

export function trashRestoreUrl(account) {
  return endpoint(account, `remote.php/dav/trashbin/${encodeURIComponent(account.username)}/restore`)
}

export function versionsRootUrl(account, fileId) {
  return endpoint(account, `remote.php/dav/versions/${encodeURIComponent(account.username)}/versions/${encodeURIComponent(String(fileId))}`)
}

export function versionItemUrl(account, fileId, versionId) {
  return `${versionsRootUrl(account, fileId)}/${encodeURIComponent(String(versionId))}`
}

export function versionRestoreUrl(account) {
  return endpoint(account, `remote.php/dav/versions/${encodeURIComponent(account.username)}/restore`)
}

function agentFor(exec) {
  if (typeof exec?.agent !== 'object' || exec.agent === null) {
    throw new CloudDriveError('AGENT_CONTEXT_REQUIRED', 'cloud tools require a DSH Agent execution context')
  }
  return exec.agent
}

export function accountFor(exec) {
  const account = accounts.get(agentFor(exec))
  if (account === undefined) throw new CloudDriveError('NOT_LOGGED_IN', 'call cloud_login first')
  return account
}

export function setAccount(exec, account) {
  accounts.set(agentFor(exec), account)
}

export function clearAccount(exec) {
  const agent = agentFor(exec)
  const account = accounts.get(agent)
  accounts.delete(agent)
  return account
}

function curlQuote(value) {
  if (/\0|\r|\n/.test(value)) throw new CloudDriveError('INVALID_CREDENTIALS', 'credentials must not contain NUL or line breaks')
  return `"${value.replaceAll('\\', '\\\\').replaceAll('"', '\\"')}"`
}

function safeHeader(value) {
  if (typeof value !== 'string' || /\0|\r|\n/.test(value)) {
    throw new CloudDriveError('INVALID_HEADER', 'request headers must not contain NUL or line breaks')
  }
  return value
}

function parseHeaderFile(text) {
  const blocks = text.split(/\r?\n\r?\n/).filter(block => /^HTTP\//.test(block))
  const lines = (blocks.at(-1) ?? '').split(/\r?\n/)
  const headers = Object.create(null)
  for (const line of lines.slice(1)) {
    const split = line.indexOf(':')
    if (split <= 0) continue
    const key = line.slice(0, split).trim().toLowerCase()
    const value = line.slice(split + 1).trim()
    headers[key] = headers[key] === undefined ? value : `${headers[key]}, ${value}`
  }
  return headers
}

export async function runCurl(request, config) {
  const directory = await mkdtemp(join(tmpdir(), 'emuvista-cloud-'))
  const responsePath = join(directory, 'response-body')
  const headerPath = join(directory, 'response-headers')
  let requestPath
  try {
    let body = request.body
    let headers = [...(request.headers ?? [])]
    if (request.form !== undefined) {
      body = Buffer.from(new URLSearchParams(request.form).toString(), 'utf8')
      headers.push('Content-Type: application/x-www-form-urlencoded')
    }
    if (body !== undefined) {
      requestPath = join(directory, 'request-body')
      await writeFile(requestPath, body, { mode: 0o600 })
    }
    const args = [
      '--silent', '--show-error',
      '--max-time', String(Math.ceil(config.timeoutMs / 1000)),
      '--connect-timeout', String(Math.max(1, Math.min(15, Math.ceil(config.timeoutMs / 1000)))),
      '--noproxy', new URL(request.account.baseUrl).hostname,
      '--config', '-',
      '--request', request.method,
      '--dump-header', headerPath,
      '--output', responsePath,
      '--write-out', '%{http_code}',
    ]
    for (const header of headers) args.push('--header', safeHeader(header))
    if (requestPath !== undefined) args.push('--data-binary', `@${requestPath}`)
    args.push(request.url)

    const result = await new Promise((resolve, reject) => {
      const child = spawn(config.curlPath, args, { stdio: ['pipe', 'pipe', 'pipe'] })
      const stdout = []
      const stderr = []
      let stdoutBytes = 0
      let stderrBytes = 0
      let spawnError
      child.stdin.on('error', error => {
        const code = (error as NodeJS.ErrnoException).code
        if (code !== 'EPIPE' && code !== 'ECONNRESET') spawnError ??= error
      })
      child.stdout.on('data', chunk => {
        stdoutBytes += chunk.length
        if (stdoutBytes <= 128) stdout.push(chunk)
      })
      child.stderr.on('data', chunk => {
        if (stderrBytes >= MAX_ERROR_BYTES) return
        const slice = chunk.subarray(0, MAX_ERROR_BYTES - stderrBytes)
        stderr.push(slice)
        stderrBytes += slice.length
      })
      child.on('error', error => { spawnError = error })
      const abort = () => child.kill('SIGTERM')
      request.signal?.addEventListener('abort', abort, { once: true })
      child.on('close', (code, signal) => {
        request.signal?.removeEventListener('abort', abort)
        if (request.signal?.aborted) return reject(request.signal.reason ?? new CloudDriveError('ABORTED', 'cloud request aborted'))
        if (spawnError !== undefined) return reject(spawnError)
        if (code !== 0) {
          const detail = Buffer.concat(stderr).toString('utf8').trim()
          return reject(new CloudDriveError('NETWORK_ERROR', `curl ended with ${signal === null ? `exit code ${code}` : `signal ${signal}`}${detail === '' ? '' : `: ${detail}`}`))
        }
        resolve(Buffer.concat(stdout).toString('ascii'))
      })
      const credentials = `user = ${curlQuote(`${request.account.username}:${request.account.password}`)}\n`
      child.stdin.end(credentials)
    })

    const responseStat = await stat(responsePath).catch(() => ({ size: 0 }))
    const maximum = request.maxOutputBytes ?? config.maxMetadataBytes
    if (responseStat.size > maximum) {
      throw new CloudDriveError('RESPONSE_TOO_LARGE', `cloud response exceeded ${maximum} bytes`, { size: responseStat.size })
    }
    const [responseBody, headerText] = await Promise.all([
      readFile(responsePath).catch(() => Buffer.alloc(0)),
      readFile(headerPath, 'utf8').catch(() => ''),
    ])
    const status = Number(result)
    if (!Number.isInteger(status) || status < 100) throw new CloudDriveError('INVALID_HTTP_STATUS', `curl returned invalid HTTP status ${JSON.stringify(result)}`)
    return { status, headers: parseHeaderFile(headerText), body: responseBody }
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
}

export function expectStatus(response, allowed, operation) {
  if (!allowed.includes(response.status)) {
    const preview = response.body.toString('utf8', 0, Math.min(response.body.length, 2048)).replace(/\s+/g, ' ').trim()
    const suffix = preview === '' ? '' : `: ${preview}`
    throw new CloudDriveError('HTTP_ERROR', `${operation} returned HTTP ${response.status}${suffix}`, { httpStatus: response.status })
  }
  return response
}

export async function requestOcs(account, config, signal, { method = 'GET', path, form, maxOutputBytes }: any = {}) {
  const response = await runCurl({
    account, signal, method, url: endpoint(account, path), form,
    headers: ['OCS-APIRequest: true', 'Accept: application/json'],
    maxOutputBytes: maxOutputBytes ?? config.maxMetadataBytes,
  }, config)
  let payload
  try { payload = JSON.parse(response.body.toString('utf8')) } catch {
    throw new CloudDriveError('INVALID_OCS_RESPONSE', `OCS endpoint returned invalid JSON with HTTP ${response.status}`)
  }
  const meta = payload?.ocs?.meta
  const code = Number(meta?.statuscode)
  if (response.status < 200 || response.status >= 300 || meta?.status !== 'ok' || (Number.isFinite(code) && code !== 100 && code !== 200)) {
    throw new CloudDriveError('OCS_ERROR', `${meta?.message ?? `HTTP ${response.status}`}`, {
      httpStatus: response.status,
      ocsStatusCode: Number.isFinite(code) ? code : null,
    })
  }
  return payload.ocs.data
}

export function escapeXml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;')
}

function localName(name) {
  const index = name.indexOf(':')
  return index < 0 ? name : name.slice(index + 1)
}

export function parseXml(xml) {
  const root = { name: '#document', text: '', children: [] }
  const stack = [root]
  const parser = new SaxesParser({ xmlns: false })
  parser.on('doctype', () => { throw new CloudDriveError('UNSAFE_XML', 'DOCTYPE is not allowed in CloudDrive responses') })
  parser.on('opentag', tag => {
    const node = { name: localName(tag.name), text: '', children: [] }
    stack.at(-1).children.push(node)
    stack.push(node)
  })
  parser.on('text', text => { stack.at(-1).text += text })
  parser.on('cdata', text => { stack.at(-1).text += text })
  parser.on('closetag', () => { stack.pop() })
  parser.write(xml).close()
  return root
}

function child(node, name) {
  return node?.children?.find(item => item.name === name)
}

function children(node, name) {
  return node?.children?.filter(item => item.name === name) ?? []
}

function text(node, name) {
  const target = name === undefined ? node : child(node, name)
  return target?.text?.trim() ?? ''
}

function successfulProperties(responseNode) {
  for (const propstat of children(responseNode, 'propstat')) {
    if (/\s2\d\d(?:\s|$)/.test(text(propstat, 'status'))) return child(propstat, 'prop')
  }
  return undefined
}

function decodePathSegments(value) {
  return value.split('/').filter(Boolean).map(segment => decodeURIComponent(segment))
}

function pathAfter(pathname, marker) {
  const full = decodePathSegments(pathname)
  const wanted = decodePathSegments(marker)
  for (let i = 0; i <= full.length - wanted.length; i++) {
    if (wanted.every((segment, offset) => full[i + offset] === segment)) return full.slice(i + wanted.length)
  }
  return []
}

export function parseDavResponses(account, body, area = 'files') {
  let document
  try { document = parseXml(body.toString('utf8')) } catch (error) {
    if (error instanceof CloudDriveError) throw error
    throw new CloudDriveError('INVALID_DAV_RESPONSE', `WebDAV returned invalid XML: ${error.message}`)
  }
  const multistatus = child(document, 'multistatus')
  if (multistatus === undefined) throw new CloudDriveError('INVALID_DAV_RESPONSE', 'WebDAV response has no multistatus element')
  const entries = []
  for (const responseNode of children(multistatus, 'response')) {
    const prop = successfulProperties(responseNode)
    if (prop === undefined) continue
    const href = text(responseNode, 'href')
    let pathname
    try { pathname = new URL(href, `${account.baseUrl}/`).pathname } catch { pathname = href }
    let remaining
    if (area === 'files') remaining = pathAfter(pathname, `remote.php/dav/files/${account.username}`)
    else if (area === 'trash') remaining = pathAfter(pathname, `remote.php/dav/trashbin/${account.username}/trash`)
    else remaining = pathAfter(pathname, `remote.php/dav/versions/${account.username}/versions`)
    const resourceType = child(prop, 'resourcetype')
    const directory = child(resourceType, 'collection') !== undefined
    const lengthText = text(prop, 'getcontentlength') || text(prop, 'size')
    const size = /^\d+$/.test(lengthText) ? Number(lengthText) : 0
    const modifiedText = text(prop, 'getlastmodified') || text(prop, 'creationdate')
    const modified = modifiedText === '' ? null : new Date(modifiedText)
    const modifiedAt = modified !== null && !Number.isNaN(modified.valueOf()) ? modified.toISOString() : null
    const remotePath = area === 'files' ? `/${remaining.join('/')}`.replace(/^\/$/, '/') : undefined
    entries.push({
      href,
      ...(remotePath === undefined ? {} : { remotePath }),
      id: remaining.at(-1) ?? '',
      name: text(prop, 'displayname') || remaining.at(-1) || '/',
      type: directory ? 'directory' : 'file',
      size,
      modifiedAt,
      etag: text(prop, 'getetag') || null,
      contentType: text(prop, 'getcontenttype') || null,
      fileId: text(prop, 'fileid') || null,
      permissions: text(prop, 'permissions') || null,
      ownerId: text(prop, 'owner-id') || null,
      ownerDisplayName: text(prop, 'owner-display-name') || null,
      favorite: text(prop, 'favorite') === '1',
      originalLocation: text(prop, 'trashbin-original-location') || null,
      originalName: text(prop, 'trashbin-filename') || null,
      versionLabel: text(prop, 'version-label') || null,
      versionAuthor: text(prop, 'version-author') || null,
      deletedAt: (() => {
        const value = text(prop, 'trashbin-deletion-time')
        if (!/^\d+$/.test(value)) return null
        return new Date(Number(value) * 1000).toISOString()
      })(),
    })
  }
  return entries
}

export const DAV_PROPFIND_BODY = Buffer.from(`<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" xmlns:nc="http://nextcloud.org/ns">
  <d:prop>
    <d:displayname/><d:getlastmodified/><d:getcontentlength/><d:getcontenttype/>
    <d:resourcetype/><d:getetag/><d:creationdate/>
    <oc:fileid/><oc:permissions/><oc:size/><oc:favorite/>
    <oc:owner-id/><oc:owner-display-name/>
    <nc:trashbin-filename/><nc:trashbin-original-location/><nc:trashbin-deletion-time/>
    <nc:version-label/><nc:version-author/>
  </d:prop>
</d:propfind>`, 'utf8')

export async function propfind(account, config, signal, url, depth, area = 'files') {
  const response = expectStatus(await runCurl({
    account, signal, method: 'PROPFIND', url,
    headers: [`Depth: ${depth}`, 'Content-Type: application/xml; charset=utf-8'],
    body: DAV_PROPFIND_BODY,
    maxOutputBytes: config.maxMetadataBytes,
  }, config), [207], 'WebDAV PROPFIND')
  return parseDavResponses(account, response.body, area)
}

export async function statRemote(account, config, signal, remotePath) {
  const entries = await propfind(account, config, signal, davUrl(account, remotePath), 0, 'files')
  const entry = entries[0]
  if (entry === undefined) throw new CloudDriveError('NOT_FOUND', `no WebDAV properties returned for ${remotePath}`)
  return entry
}

export async function ensureDirectories(account, config, signal, remotePath) {
  const parent = dirname(remotePath)
  if (parent === '/' || parent === '.') return []
  const segments = parent.split('/').filter(Boolean)
  const created = []
  let current = ''
  for (const segment of segments) {
    current += `/${segment}`
    const response = await runCurl({ account, signal, method: 'MKCOL', url: davUrl(account, current), maxOutputBytes: 64 * 1024 }, config)
    if (response.status === 201) {
      created.push(current)
      continue
    }
    if (response.status === 405) {
      const existing = await statRemote(account, config, signal, current)
      if (existing.type !== 'directory') throw new CloudDriveError('PATH_CONFLICT', `${current} exists and is not a directory`)
      continue
    }
    expectStatus(response, [201], `create directory ${current}`)
  }
  return created
}

export function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

function managedVersionPath(config, account, remotePath) {
  const key = sha256(Buffer.from(`${account.baseUrl}\0${account.username}\0${remotePath}`, 'utf8'))
  return join(config.versionDirectory, key)
}

export async function saveManagedVersion(config, account, remotePath, bytes, metadata: Record<string, any> = {}) {
  if (!Buffer.isBuffer(bytes)) throw new CloudDriveError('INVALID_ARGUMENT', 'managed version bytes must be a Buffer')
  if (bytes.length > config.maxTransferBytes) throw new CloudDriveError('TRANSFER_TOO_LARGE', `version snapshot exceeds ${config.maxTransferBytes} bytes`)
  const directory = managedVersionPath(config, account, remotePath)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const versionId = `dsh-${Date.now()}-${randomUUID()}`
  const bodyPath = join(directory, `${versionId}.bin`)
  const metaPath = join(directory, `${versionId}.json`)
  const record = {
    versionId, remotePath, size: bytes.length, sha256: sha256(bytes),
    modifiedAt: metadata.modifiedAt ?? new Date().toISOString(),
    etag: metadata.etag ?? null, source: 'managed',
  }
  await writeFile(bodyPath, bytes, { mode: 0o600 })
  await writeFile(metaPath, JSON.stringify(record), { mode: 0o600 })
  return record
}

export async function listManagedVersions(config, account, remotePath) {
  const directory = managedVersionPath(config, account, remotePath)
  const names = await readdir(directory).catch(error => {
    if (error.code === 'ENOENT') return []
    throw error
  })
  const records = []
  for (const name of names.filter(name => name.endsWith('.json'))) {
    try {
      const record = JSON.parse(await readFile(join(directory, name), 'utf8'))
      if (record.remotePath === remotePath && typeof record.versionId === 'string') records.push(record)
    } catch {
      // Ignore incomplete records; snapshots are useful only when both files are readable.
    }
  }
  return records.sort((a, b) => String(b.modifiedAt).localeCompare(String(a.modifiedAt)))
}

export async function readManagedVersion(config, account, remotePath, versionId) {
  const id = requiredText(versionId, 'version_id')
  if (!/^dsh-[0-9]+-[0-9a-f-]{36}$/.test(id)) throw new CloudDriveError('VERSION_NOT_FOUND', `managed version ${id} is invalid`)
  const directory = managedVersionPath(config, account, remotePath)
  let record
  try {
    record = JSON.parse(await readFile(join(directory, `${id}.json`), 'utf8'))
    const bytes = await readFile(join(directory, `${id}.bin`))
    if (record.remotePath !== remotePath || record.versionId !== id || sha256(bytes) !== record.sha256) {
      throw new CloudDriveError('VERSION_CORRUPT', `managed version ${id} failed integrity validation`)
    }
    return { record, bytes }
  } catch (error) {
    if (error instanceof CloudDriveError) throw error
    if (error.code === 'ENOENT') throw new CloudDriveError('VERSION_NOT_FOUND', `managed version ${id} does not belong to ${remotePath}`)
    throw error
  }
}

export function decodeUploadContent(content, encoding) {
  if (typeof content !== 'string') throw new CloudDriveError('INVALID_ARGUMENT', 'content must be a string')
  if (encoding === 'utf8') return Buffer.from(content, 'utf8')
  if (encoding !== 'base64') throw new CloudDriveError('INVALID_ARGUMENT', 'encoding must be utf8 or base64')
  if (content.length % 4 !== 0 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(content)) {
    throw new CloudDriveError('INVALID_BASE64', 'content is not valid padded base64')
  }
  return Buffer.from(content, 'base64')
}

export function decodeUtf8(bytes) {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes) } catch {
    throw new CloudDriveError('INVALID_UTF8', 'downloaded content is not valid UTF-8; request base64 or workspace output')
  }
}

export async function writeControlledDownload(config, account, remotePath, bytes, localName) {
  const requestedName = localName === undefined ? basename(remotePath) : requiredText(localName, 'local_name')
  if (requestedName !== basename(requestedName) || requestedName === '.' || requestedName === '..') {
    throw new CloudDriveError('INVALID_LOCAL_NAME', 'local_name must be one filename without path separators')
  }
  const directory = join(config.downloadDirectory, account.username)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const target = join(directory, requestedName)
  await writeFile(target, bytes, { mode: 0o600 })
  return target
}

const PERMISSIONS = { read: 1, update: 2, create: 4, delete: 8, share: 16 }

export function permissionsToMask(value, fallback = ['read']) {
  const permissions = value ?? fallback
  if (!Array.isArray(permissions) || permissions.length === 0) {
    throw new CloudDriveError('INVALID_PERMISSIONS', 'permissions must be a non-empty array')
  }
  let mask = 0
  for (const permission of new Set(permissions)) {
    if (!Object.hasOwn(PERMISSIONS, permission)) {
      throw new CloudDriveError('INVALID_PERMISSIONS', `unknown permission ${JSON.stringify(permission)}`)
    }
    mask |= PERMISSIONS[permission]
  }
  return mask
}

export function maskToPermissions(maskValue) {
  const mask = Number(maskValue)
  return Object.entries(PERMISSIONS).filter(([, bit]) => (mask & bit) !== 0).map(([name]) => name)
}

export function mapShare(data, direction = 'outgoing') {
  const item = data ?? {}
  const shareId = String(item.id ?? item.share_id ?? '')
  return {
    shareId,
    direction,
    shareType: Number(item.share_type ?? item.shareType ?? 0),
    owner: String(item.uid_owner ?? item.owner ?? ''),
    recipient: String(item.share_with ?? item.shareWith ?? ''),
    sourcePath: String(item.path ?? item.source_path ?? ''),
    targetPath: String(item.file_target ?? item.item_target ?? item.path ?? ''),
    permissions: maskToPermissions(item.permissions ?? 0),
    permissionMask: Number(item.permissions ?? 0),
    note: item.note == null ? null : String(item.note),
    label: item.label == null ? null : String(item.label),
    token: item.token == null ? null : String(item.token),
    url: item.url == null ? null : String(item.url),
    expireDate: item.expiration == null ? null : String(item.expiration),
    createdAt: /^\d+$/.test(String(item.stime ?? '')) ? new Date(Number(item.stime) * 1000).toISOString() : null,
  }
}

export async function getShare(account, config, signal, shareId) {
  const id = requiredText(String(shareId), 'share_id')
  const data = await requestOcs(account, config, signal, {
    path: `ocs/v2.php/apps/files_sharing/api/v1/shares/${encodeURIComponent(id)}?format=json`,
  })
  const row = Array.isArray(data) ? data[0] : data
  if (row === undefined || row === null || typeof row !== 'object') {
    throw new CloudDriveError('INVALID_OCS_RESPONSE', `share ${id} response did not contain a share object`)
  }
  return mapShare(row, row.uid_owner === account.username ? 'outgoing' : 'incoming')
}

export function paginate(items, limitValue, cursorValue) {
  const limit = positiveInteger(limitValue, 100, 'limit', 200)
  const cursor = cursorValue === undefined || cursorValue === null ? 0 : Number(cursorValue)
  if (!Number.isSafeInteger(cursor) || cursor < 0) throw new CloudDriveError('INVALID_CURSOR', 'cursor must be a non-negative integer string')
  const page = items.slice(cursor, cursor + limit)
  const nextCursor = cursor + page.length < items.length ? String(cursor + page.length) : null
  return { items: page, nextCursor, total: items.length }
}

const createCoreToolsModule = (() => {

const objectOutput = (render: (value: any) => string) => ({
  schema: { type: 'json' as const },
  render: (_args: unknown, value: any) => [{ type: 'text' as const, text: render(value) }],
})

const listOutput = label => objectOutput(value => `${label}: ${JSON.stringify(value)}`)

function publicEntry(entry) {
  return {
    path: entry.remotePath,
    name: entry.name,
    type: entry.type,
    size: entry.size,
    modifiedAt: entry.modifiedAt,
    etag: entry.etag,
    contentType: entry.contentType,
    fileId: entry.fileId,
    permissions: entry.permissions,
    ownerId: entry.ownerId,
    ownerDisplayName: entry.ownerDisplayName,
    favorite: entry.favorite,
  }
}

function shareType(value) {
  const name = value ?? 'user'
  const values = { user: 0, group: 1, public_link: 3, email: 4, federated: 6, circle: 7, talk: 10 }
  if (!Object.hasOwn(values, name)) throw new CloudDriveError('INVALID_SHARE_TYPE', `unsupported share_type ${JSON.stringify(name)}`)
  return { name, code: values[name] }
}

function shareForm(args, remotePath) {
  const type = shareType(args.share_type)
  const recipient = optionalText(args.recipient, 'recipient')
  if (type.name !== 'public_link' && recipient === undefined) {
    throw new CloudDriveError('INVALID_ARGUMENT', `recipient is required for share_type ${type.name}`)
  }
  const mask = permissionsToMask(args.permissions, ['read'])
  const form: Record<string, string> = {
    path: remotePath,
    shareType: String(type.code),
    permissions: String(mask),
  }
  if (recipient !== undefined) form.shareWith = recipient
  if (args.expire_date !== undefined) form.expireDate = requiredText(args.expire_date, 'expire_date')
  if (args.note !== undefined) form.note = requiredText(args.note, 'note')
  if (args.label !== undefined) form.label = requiredText(args.label, 'label')
  if (args.password !== undefined) form.password = requiredText(args.password, 'password')
  return { form, type, recipient: recipient ?? '', mask }
}

async function listSharesForDirection(account, config, signal, direction) {
  const query = direction === 'incoming' ? '&shared_with_me=true' : ''
  const data = await requestOcs(account, config, signal, {
    path: `ocs/v2.php/apps/files_sharing/api/v1/shares?format=json${query}`,
  })
  const rows = Array.isArray(data) ? data : data && Object.keys(data).length > 0 ? [data] : []
  return rows.map(row => mapShare(row, direction))
}

function createCoreTools(configInput = {}) {
  const config = runtimeConfig(configInput)

  const login = defineTool({
    name: 'cloud_login',
    description: 'Log this Agent into one Nextcloud-compatible EmuVista Cloud Drive account. The password must be supplied explicitly.',
    parameters: {
      server_url: { type: 'string', description: 'Cloud base URL. Defaults to DSH_CLOUD_BASE_URL.' },
      username: { type: 'string', description: 'Account username. Defaults to DSH_CLOUD_USERNAME.' },
      password: { type: 'string', required: true, description: 'Account password supplied explicitly for this login.' },
    },
    output: objectOutput(value => `Logged into ${value.serverUrl} as ${value.username}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = {
        baseUrl: normalizeBaseUrl(args.server_url ?? config.baseUrl),
        username: requiredText(args.username ?? config.username, 'username'),
        password: requiredText(args.password, 'password'),
      }
      const response = await runCurl({
        account, signal: exec.signal, method: 'PROPFIND', url: davUrl(account),
        headers: ['Depth: 0'], maxOutputBytes: 128 * 1024,
      }, config)
      expectStatus(response, [207], 'CloudDrive login check')
      setAccount(exec, account)
      return { serverUrl: account.baseUrl, username: account.username }
    },
  })

  const logout = defineTool({
    name: 'cloud_logout',
    description: 'Forget this Agent\'s in-memory Cloud Drive login and credentials.',
    parameters: {},
    output: objectOutput(value => value.loggedOut ? `Logged out ${value.username}.` : 'No Cloud Drive login was active.'),
    async execute(_args, exec) {
      const account = clearAccount(exec)
      return { loggedOut: account !== undefined, username: account?.username ?? null }
    },
  })

  const account = defineTool({
    name: 'cloud_account',
    description: 'Read the logged-in Cloud Drive identity, quota, server version, and advertised capabilities.',
    parameters: {},
    output: listOutput('Cloud account'),
    timeoutMs: config.timeoutMs,
    async execute(_args, exec) {
      const current = accountFor(exec)
      const [user, capabilities] = await Promise.all([
        requestOcs(current, config, exec.signal, {
          path: `ocs/v2.php/cloud/users/${encodeURIComponent(current.username)}?format=json`,
        }),
        requestOcs(current, config, exec.signal, { path: 'ocs/v2.php/cloud/capabilities?format=json' }),
      ])
      const quota = user?.quota ?? {}
      return {
        serverUrl: current.baseUrl,
        username: String(user?.id ?? current.username),
        displayName: String(user?.displayname ?? user?.displayName ?? current.username),
        quota: {
          free: Number(quota.free ?? 0),
          used: Number(quota.used ?? 0),
          total: Number(quota.total ?? 0),
          relative: Number(quota.relative ?? 0),
        },
        version: capabilities?.version ?? null,
        capabilities: capabilities?.capabilities ?? {},
      }
    },
  })

  const list = defineTool({
    name: 'cloud_list',
    description: 'List the direct children of a Cloud Drive directory, including the root directory.',
    parameters: {
      remote_path: { type: 'string', description: 'Directory path. Defaults to /.' },
      limit: { type: 'integer', description: 'Maximum entries from 1 through 200. Defaults to 100.' },
      cursor: { type: 'string', description: 'Opaque cursor returned by a previous call.' },
    },
    output: listOutput('Cloud directory'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const path = normalizeRemotePath(args.remote_path ?? '/', { allowRoot: true })
      const all = await propfind(current, config, exec.signal, davUrl(current, path), 1)
      const children = all.filter(entry => entry.remotePath !== path).map(publicEntry)
      const page = paginate(children, args.limit, args.cursor)
      return { path, entries: page.items, nextCursor: page.nextCursor, total: page.total }
    },
  })

  const stat = defineTool({
    name: 'cloud_stat',
    description: 'Read metadata for one Cloud Drive file or directory.',
    parameters: { remote_path: { type: 'string', required: true, description: 'File or directory path; / is allowed.' } },
    output: listOutput('Cloud item'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const path = normalizeRemotePath(args.remote_path, { allowRoot: true })
      return publicEntry(await statRemote(current, config, exec.signal, path))
    },
  })

  const mkdirTool = defineTool({
    name: 'cloud_mkdir',
    description: 'Create one Cloud Drive directory, optionally creating missing parent directories.',
    parameters: {
      remote_path: { type: 'string', required: true, description: 'New directory path.' },
      create_parents: { type: 'boolean', description: 'Create missing parents. Defaults to false.' },
    },
    output: objectOutput(value => `Created directory ${value.path}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const path = normalizeRemotePath(args.remote_path)
      const createdPaths = []
      if (args.create_parents === true) createdPaths.push(...await ensureDirectories(current, config, exec.signal, `${path}/placeholder`))
      else {
        const response = await runCurl({ account: current, signal: exec.signal, method: 'MKCOL', url: davUrl(current, path) }, config)
        if (response.status === 405) throw new CloudDriveError('ALREADY_EXISTS', `${path} already exists`)
        expectStatus(response, [201], `create directory ${path}`)
        createdPaths.push(path)
      }
      const item = await statRemote(current, config, exec.signal, path)
      if (item.type !== 'directory') throw new CloudDriveError('PATH_CONFLICT', `${path} is not a directory after creation`)
      return { path, created: createdPaths.includes(path), createdPaths, etag: item.etag }
    },
  })

  const upload = defineTool({
    name: 'cloud_upload',
    description: 'Upload complete UTF-8 or padded Base64 content with overwrite and ETag conflict protection.',
    parameters: {
      remote_path: { type: 'string', required: true, description: 'Destination file path.' },
      content: { type: 'string', required: true, description: 'Complete content encoded according to encoding.' },
      encoding: { type: 'string', description: 'utf8 (default) or base64.' },
      overwrite: { type: 'boolean', description: 'Allow replacing an existing file. Defaults to false.' },
      expected_etag: { type: 'string', description: 'Only overwrite when the current ETag matches.' },
      create_parents: { type: 'boolean', description: 'Create missing parent directories. Defaults to false.' },
    },
    output: objectOutput(value => `Uploaded ${value.remotePath} (${value.size} bytes, sha256 ${value.sha256}).`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const remotePath = normalizeRemotePath(args.remote_path)
      const encoding = args.encoding ?? 'utf8'
      const body = decodeUploadContent(args.content, encoding)
      if (body.length > config.maxTransferBytes) throw new CloudDriveError('TRANSFER_TOO_LARGE', `upload exceeds ${config.maxTransferBytes} bytes`)
      if (args.create_parents === true) await ensureDirectories(current, config, exec.signal, remotePath)
      const headers = ['Content-Type: application/octet-stream']
      if (args.expected_etag !== undefined) headers.push(`If-Match: ${requiredText(args.expected_etag, 'expected_etag')}`)
      else if (args.overwrite !== true) headers.push('If-None-Match: *')
      if (args.overwrite === true) {
        let previous
        try { previous = await statRemote(current, config, exec.signal, remotePath) } catch (error) {
          if (!(error instanceof CloudDriveError) || error.details?.httpStatus !== 404) throw error
        }
        if (previous !== undefined) {
          if (args.expected_etag !== undefined && previous.etag !== args.expected_etag) {
            throw new CloudDriveError('PRECONDITION_FAILED', `upload precondition failed for ${remotePath}`)
          }
          if (previous.type !== 'file') throw new CloudDriveError('PATH_CONFLICT', `${remotePath} exists and is not a file`)
          const old = expectStatus(await runCurl({
            account: current, signal: exec.signal, method: 'GET', url: davUrl(current, remotePath), maxOutputBytes: config.maxTransferBytes,
          }, config), [200], `snapshot ${remotePath}`)
          await saveManagedVersion(config, current, remotePath, old.body, previous)
        }
      }
      const response = await runCurl({
        account: current, signal: exec.signal, method: 'PUT', url: davUrl(current, remotePath),
        headers, body, maxOutputBytes: 64 * 1024,
      }, config)
      if (response.status === 412) throw new CloudDriveError('PRECONDITION_FAILED', `upload precondition failed for ${remotePath}`)
      expectStatus(response, [201, 204], `upload ${remotePath}`)
      const metadata = await statRemote(current, config, exec.signal, remotePath)
      return {
        remotePath,
        size: body.length,
        sha256: sha256(body),
        etag: metadata.etag,
        created: response.status === 201,
        overwritten: response.status === 204,
        httpStatus: response.status,
      }
    },
  })

  const download = defineTool({
    name: 'cloud_download',
    description: 'Download one Cloud Drive file as bounded UTF-8, bounded Base64, or a file in the controlled download workspace.',
    parameters: {
      remote_path: { type: 'string', required: true, description: 'File path, including an incoming shared-file target.' },
      output: { type: 'string', description: 'text (default), base64, or workspace.' },
      local_name: { type: 'string', description: 'Filename for workspace output.' },
    },
    output: objectOutput(value => value.output === 'workspace'
      ? `Downloaded ${value.remotePath} to ${value.localPath} (${value.size} bytes).`
      : `Downloaded ${value.remotePath} (${value.size} bytes, sha256 ${value.sha256}) as ${value.output}:\n${value.content}`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const remotePath = normalizeRemotePath(args.remote_path)
      const output = args.output ?? 'text'
      if (!['text', 'base64', 'workspace'].includes(output)) throw new CloudDriveError('INVALID_ARGUMENT', 'output must be text, base64, or workspace')
      const response = expectStatus(await runCurl({
        account: current, signal: exec.signal, method: 'GET', url: davUrl(current, remotePath),
        maxOutputBytes: config.maxTransferBytes,
      }, config), [200], `download ${remotePath}`)
      const bytes = response.body
      const digest = sha256(bytes)
      if (output === 'workspace') {
        const localPath = await writeControlledDownload(config, current, remotePath, bytes, args.local_name)
        return { remotePath, output, size: bytes.length, sha256: digest, content: null, localPath }
      }
      if (bytes.length > config.maxInlineBytes) {
        throw new CloudDriveError('INLINE_RESULT_TOO_LARGE', `inline download exceeds ${config.maxInlineBytes} bytes; use workspace output`)
      }
      const content = output === 'base64' ? bytes.toString('base64') : decodeUtf8(bytes)
      return { remotePath, output, size: bytes.length, sha256: digest, content, localPath: null }
    },
  })

  const move = defineTool({
    name: 'cloud_move',
    description: 'Move or rename one Cloud Drive file or directory.',
    parameters: {
      source_path: { type: 'string', required: true },
      destination_path: { type: 'string', required: true },
      overwrite: { type: 'boolean', description: 'Allow replacing the destination. Defaults to false.' },
      expected_etag: { type: 'string', description: 'Only move when the source ETag matches.' },
    },
    output: objectOutput(value => `Moved ${value.sourcePath} to ${value.destinationPath}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const sourcePath = normalizeRemotePath(args.source_path, { name: 'source_path' })
      const destinationPath = normalizeRemotePath(args.destination_path, { name: 'destination_path' })
      if (sourcePath === destinationPath) throw new CloudDriveError('INVALID_ARGUMENT', 'source_path and destination_path must differ')
      const source = await statRemote(current, config, exec.signal, sourcePath)
      if (args.expected_etag !== undefined && source.etag !== requiredText(args.expected_etag, 'expected_etag')) {
        throw new CloudDriveError('ETAG_MISMATCH', `source ETag does not match for ${sourcePath}`)
      }
      const headers = [`Destination: ${davUrl(current, destinationPath)}`, `Overwrite: ${args.overwrite === true ? 'T' : 'F'}`]
      if (args.expected_etag !== undefined) headers.push(`If-Match: ${args.expected_etag}`)
      const response = await runCurl({ account: current, signal: exec.signal, method: 'MOVE', url: davUrl(current, sourcePath), headers }, config)
      if (response.status === 412) throw new CloudDriveError('DESTINATION_EXISTS', `${destinationPath} exists or the ETag precondition failed`)
      expectStatus(response, [201, 204], `move ${sourcePath}`)
      const destination = await statRemote(current, config, exec.signal, destinationPath)
      return { sourcePath, destinationPath, moved: true, overwritten: response.status === 204, type: destination.type, etag: destination.etag }
    },
  })

  const deleteTool = defineTool({
    name: 'cloud_delete',
    description: 'Delete one Cloud Drive file or directory through normal Nextcloud deletion, which is recoverable when trash is enabled.',
    parameters: {
      remote_path: { type: 'string', required: true },
      expected_etag: { type: 'string', description: 'Only delete when the current ETag matches.' },
    },
    output: objectOutput(value => `Deleted ${value.path}; recoverable=${value.recoverable}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const path = normalizeRemotePath(args.remote_path)
      const item = await statRemote(current, config, exec.signal, path)
      if (args.expected_etag !== undefined && item.etag !== requiredText(args.expected_etag, 'expected_etag')) {
        throw new CloudDriveError('ETAG_MISMATCH', `ETag does not match for ${path}`)
      }
      const headers = args.expected_etag === undefined ? [] : [`If-Match: ${args.expected_etag}`]
      const response = expectStatus(await runCurl({ account: current, signal: exec.signal, method: 'DELETE', url: davUrl(current, path), headers }, config), [204], `delete ${path}`)
      return { path, type: item.type, deleted: true, recoverable: true, httpStatus: response.status }
    },
  })

  const share = defineTool({
    name: 'cloud_share',
    description: 'Create a user, group, public-link, email, federated, circle, or Talk share for one file or directory.',
    parameters: {
      remote_path: { type: 'string', required: true },
      recipient: { type: 'string', description: 'Required except for public_link shares.' },
      share_type: { type: 'string', description: 'user (default), group, public_link, email, federated, circle, or talk.' },
      permissions: { type: 'array', items: { type: 'string' }, description: 'Any of read, update, create, delete, share. Defaults to read.' },
      expire_date: { type: 'string', description: 'Optional YYYY-MM-DD expiry.' },
      note: { type: 'string' },
      label: { type: 'string' },
      password: { type: 'string', description: 'Optional public-link password.' },
    },
    output: listOutput('Created Cloud share'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const remotePath = normalizeRemotePath(args.remote_path)
      await statRemote(current, config, exec.signal, remotePath)
      const prepared = shareForm(args, remotePath)
      const data = await requestOcs(current, config, exec.signal, {
        method: 'POST', path: 'ocs/v2.php/apps/files_sharing/api/v1/shares?format=json', form: prepared.form,
      })
      const mapped = mapShare(data, 'outgoing')
      if (mapped.shareId === '') throw new CloudDriveError('INVALID_OCS_RESPONSE', 'share response did not contain an id')
      return mapped
    },
  })

  const listShares = defineTool({
    name: 'cloud_list_shares',
    description: 'List incoming, outgoing, or all shares so an Agent can discover shared files without knowing their paths.',
    parameters: {
      direction: { type: 'string', description: 'incoming, outgoing (default), or all.' },
      limit: { type: 'integer', description: 'Maximum entries from 1 through 200.' },
      cursor: { type: 'string' },
    },
    output: listOutput('Cloud shares'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const direction = args.direction ?? 'outgoing'
      if (!['incoming', 'outgoing', 'all'].includes(direction)) throw new CloudDriveError('INVALID_ARGUMENT', 'direction must be incoming, outgoing, or all')
      let shares
      if (direction === 'all') {
        const [incoming, outgoing] = await Promise.all([
          listSharesForDirection(current, config, exec.signal, 'incoming'),
          listSharesForDirection(current, config, exec.signal, 'outgoing'),
        ])
        const seen = new Set()
        shares = [...incoming, ...outgoing].filter(item => {
          const key = `${item.direction}:${item.shareId}`
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
      } else shares = await listSharesForDirection(current, config, exec.signal, direction)
      const page = paginate(shares, args.limit, args.cursor)
      return { direction, shares: page.items, nextCursor: page.nextCursor, total: page.total }
    },
  })

  const updateShare = defineTool({
    name: 'cloud_update_share',
    description: 'Update permissions, expiry, note, public-link password, or download permission for an existing share.',
    parameters: {
      share_id: { type: 'string', required: true },
      permissions: { type: 'array', items: { type: 'string' } },
      expire_date: { type: 'string' },
      note: { type: 'string' },
      password: { type: 'string' },
      download_allowed: { type: 'boolean' },
    },
    output: listOutput('Updated Cloud share'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const shareId = requiredText(args.share_id, 'share_id')
      const form: Record<string, string> = {}
      if (args.permissions !== undefined) form.permissions = String(permissionsToMask(args.permissions))
      if (args.expire_date !== undefined) form.expireDate = args.expire_date === '' ? '' : requiredText(args.expire_date, 'expire_date')
      if (args.note !== undefined) form.note = String(args.note)
      if (args.password !== undefined) form.password = String(args.password)
      if (args.download_allowed !== undefined) {
        form.attributes = JSON.stringify([{ scope: 'permissions', key: 'download', value: args.download_allowed }])
      }
      if (Object.keys(form).length === 0) throw new CloudDriveError('INVALID_ARGUMENT', 'at least one share field must be updated')
      await requestOcs(current, config, exec.signal, {
        method: 'PUT', path: `ocs/v2.php/apps/files_sharing/api/v1/shares/${encodeURIComponent(shareId)}?format=json`, form,
      })
      return await getShare(current, config, exec.signal, shareId)
    },
  })

  const unshare = defineTool({
    name: 'cloud_unshare',
    description: 'Revoke one share without deleting the owner\'s file.',
    parameters: { share_id: { type: 'string', required: true } },
    output: objectOutput(value => `Revoked share ${value.shareId}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const current = accountFor(exec)
      const shareId = requiredText(args.share_id, 'share_id')
      await requestOcs(current, config, exec.signal, {
        method: 'DELETE', path: `ocs/v2.php/apps/files_sharing/api/v1/shares/${encodeURIComponent(shareId)}?format=json`,
      })
      return { shareId, revoked: true }
    },
  })

  return [login, logout, account, list, stat, mkdirTool, upload, download, move, deleteTool, share, listShares, updateShare, unshare]
}


  return { createCoreTools }
})()

export const createCoreTools = createCoreToolsModule.createCoreTools

const createExtendedToolsModule = (() => {

const objectOutput = (render: (value: any) => string) => ({
  schema: { type: 'json' as const },
  render: (_args: unknown, value: any) => [{ type: 'text' as const, text: render(value) }],
})

const jsonOutput = label => objectOutput(value => `${label}: ${JSON.stringify(value)}`)

function publicEntry(entry) {
  return {
    path: entry.remotePath,
    name: entry.name,
    type: entry.type,
    size: entry.size,
    modifiedAt: entry.modifiedAt,
    etag: entry.etag,
    contentType: entry.contentType,
    fileId: entry.fileId,
    permissions: entry.permissions,
    ownerId: entry.ownerId,
    ownerDisplayName: entry.ownerDisplayName,
    favorite: entry.favorite,
  }
}

function buildSearchBody(account, scopePath, query, serverLimit = 200) {
  const encodedScope = scopePath === '/'
    ? ''
    : scopePath.split('/').filter(Boolean).map(encodeURIComponent).join('/')
  // SEARCH is sent to the DAV root, so the scope href is relative to that root.
  const href = `/files/${encodeURIComponent(account.username)}/${encodedScope}`
  return Buffer.from(`<?xml version="1.0" encoding="UTF-8"?>
<d:searchrequest xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:basicsearch>
    <d:select><d:prop>
      <d:displayname/><d:getlastmodified/><d:getcontentlength/><d:getcontenttype/>
      <d:resourcetype/><d:getetag/><oc:fileid/><oc:permissions/>
      <oc:owner-id/><oc:owner-display-name/><oc:favorite/>
    </d:prop></d:select>
    <d:from><d:scope><d:href>${escapeXml(href)}</d:href><d:depth>infinity</d:depth></d:scope></d:from>
    <d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>%${escapeXml(query)}%</d:literal></d:like></d:where>
    <d:orderby><d:order><d:prop><d:displayname/></d:prop><d:ascending/></d:order></d:orderby>
    <d:limit><d:nresults>${serverLimit}</d:nresults></d:limit>
  </d:basicsearch>
</d:searchrequest>`, 'utf8')
}

const SHARE_TYPES = {
  users: 'user', groups: 'group', remotes: 'federated', remote_groups: 'federated_group',
  emails: 'email', circles: 'circle', rooms: 'talk', lookup: 'lookup',
}

function normalizeRecipient(row, category, exact) {
  if (row === null || typeof row !== 'object') return null
  const value = row.value && typeof row.value === 'object' ? row.value : {}
  const recipient = value.shareWith ?? value.share_with ?? row.shareWith ?? row.share_with ?? row.value
  if (recipient === undefined || recipient === null || typeof recipient === 'object') return null
  return {
    recipient: String(recipient),
    displayName: String(row.label ?? value.displayName ?? value.display_name ?? recipient),
    shareType: String(value.shareType ?? value.share_type ?? SHARE_TYPES[category] ?? category),
    category,
    exact,
  }
}

function mapRecipients(data) {
  const results = []
  const append = (container, exact) => {
    if (container === null || typeof container !== 'object') return
    for (const [category, rows] of Object.entries(container)) {
      if (!Array.isArray(rows)) continue
      for (const row of rows) {
        const mapped = normalizeRecipient(row, category, exact)
        if (mapped !== null) results.push(mapped)
      }
    }
  }
  append(data?.exact, true)
  append(data, false)
  const seen = new Set()
  return results.filter(item => {
    const key = `${item.shareType}:${item.recipient}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function createExtendedTools(inputConfig = {}) {
  const config = runtimeConfig(inputConfig)

  const copy = defineTool({
    name: 'cloud_copy',
    description: 'Copy one Cloud Drive file or directory while retaining the source.',
    parameters: {
      source_path: { type: 'string', required: true },
      destination_path: { type: 'string', required: true },
      overwrite: { type: 'boolean', description: 'Allow replacing the destination. Defaults to false.' },
      expected_etag: { type: 'string', description: 'Only copy when the source ETag matches.' },
      create_parents: { type: 'boolean', description: 'Create missing destination parents. Defaults to false.' },
    },
    output: objectOutput(value => `Copied ${value.sourcePath} to ${value.destinationPath}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const sourcePath = normalizeRemotePath(args.source_path, { name: 'source_path' })
      const destinationPath = normalizeRemotePath(args.destination_path, { name: 'destination_path' })
      if (sourcePath === destinationPath) throw new CloudDriveError('INVALID_ARGUMENT', 'source_path and destination_path must differ')
      const source = await statRemote(account, config, exec.signal, sourcePath)
      if (args.expected_etag !== undefined && source.etag !== requiredText(args.expected_etag, 'expected_etag')) {
        throw new CloudDriveError('ETAG_MISMATCH', `source ETag does not match for ${sourcePath}`)
      }
      if (args.create_parents === true) await ensureDirectories(account, config, exec.signal, destinationPath)

      // Some S3-compatible backends do not implement the server-side CopyObject
      // operation used by Nextcloud's WebDAV COPY. A bounded GET/PUT copy keeps
      // the tool portable across those deployments and enforces the same
      // destination and ETag preconditions in this process.
      const overwrite = args.overwrite === true
      let transferredBytes = 0
      const copyFile = async (from, to, allowOverwrite) => {
        const downloaded = expectStatus(await runCurl({
          account, signal: exec.signal, method: 'GET', url: davUrl(account, from),
          maxOutputBytes: config.maxTransferBytes - transferredBytes,
        }, config), [200], `read copy source ${from}`)
        transferredBytes += downloaded.body.length
        if (transferredBytes > config.maxTransferBytes) {
          throw new CloudDriveError('TRANSFER_TOO_LARGE', `copy exceeds ${config.maxTransferBytes} bytes`)
        }
        const uploaded = await runCurl({
          account, signal: exec.signal, method: 'PUT', url: davUrl(account, to),
          headers: allowOverwrite ? [] : ['If-None-Match: *'], body: downloaded.body,
          maxOutputBytes: 64 * 1024,
        }, config)
        if (uploaded.status === 412) throw new CloudDriveError('PRECONDITION_FAILED', `${to} already exists`)
        expectStatus(uploaded, [201, 204], `write copy destination ${to}`)
        return uploaded.status
      }

      let overwritten = false
      if (source.type === 'file') {
        overwritten = await copyFile(sourcePath, destinationPath, overwrite) === 204
      } else {
        if (destinationPath.startsWith(`${sourcePath}/`)) {
          throw new CloudDriveError('INVALID_ARGUMENT', 'a directory cannot be copied inside itself')
        }
        if (overwrite) {
          const removed = await runCurl({ account, signal: exec.signal, method: 'DELETE', url: davUrl(account, destinationPath), maxOutputBytes: 64 * 1024 }, config)
          if (![204, 404].includes(removed.status)) expectStatus(removed, [204, 404], `replace copy destination ${destinationPath}`)
          overwritten = removed.status === 204
        }
        const rootCreated = await runCurl({ account, signal: exec.signal, method: 'MKCOL', url: davUrl(account, destinationPath), maxOutputBytes: 64 * 1024 }, config)
        if (rootCreated.status === 405 && !overwrite) throw new CloudDriveError('PRECONDITION_FAILED', `${destinationPath} already exists`)
        expectStatus(rootCreated, [201], `create copy destination ${destinationPath}`)
        const descendants = (await (async () => {
          const response = expectStatus(await runCurl({
            account, signal: exec.signal, method: 'PROPFIND', url: davUrl(account, sourcePath),
            headers: ['Depth: infinity', 'Content-Type: application/xml; charset=utf-8'],
            body: Buffer.from('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:getcontentlength/><d:resourcetype/></d:prop></d:propfind>'),
            maxOutputBytes: config.maxMetadataBytes,
          }, config), [207], `enumerate copy source ${sourcePath}`)
          return parseDavResponses(account, response.body, 'files')
        })()).filter(item => item.remotePath !== sourcePath)
        const directories = descendants.filter(item => item.type === 'directory').sort((a, b) => a.remotePath.length - b.remotePath.length)
        for (const item of directories) {
          const relative = item.remotePath.slice(sourcePath.length)
          expectStatus(await runCurl({ account, signal: exec.signal, method: 'MKCOL', url: davUrl(account, `${destinationPath}${relative}`), maxOutputBytes: 64 * 1024 }, config), [201], `copy directory ${item.remotePath}`)
        }
        for (const item of descendants.filter(item => item.type === 'file')) {
          const relative = item.remotePath.slice(sourcePath.length)
          await copyFile(item.remotePath, `${destinationPath}${relative}`, false)
        }
      }
      const destination = await statRemote(account, config, exec.signal, destinationPath)
      return {
        sourcePath, destinationPath, copied: true, overwritten,
        type: destination.type, size: destination.size, etag: destination.etag, transferredBytes,
      }
    },
  })

  const search = defineTool({
    name: 'cloud_search',
    description: 'Search recursively by case-insensitive name within a Cloud Drive directory.',
    parameters: {
      query: { type: 'string', required: true, description: 'Filename or directory-name text to find.' },
      remote_path: { type: 'string', description: 'Search scope. Defaults to /.' },
      item_type: { type: 'string', description: 'all (default), file, or directory.' },
      modified_after: { type: 'string', description: 'Optional inclusive ISO-8601 timestamp.' },
      limit: { type: 'integer', description: 'Maximum results from 1 through 200. Defaults to 100.' },
      cursor: { type: 'string' },
    },
    output: jsonOutput('Cloud search'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const query = requiredText(args.query, 'query')
      const scopePath = normalizeRemotePath(args.remote_path ?? '/', { allowRoot: true })
      const itemType = args.item_type ?? 'all'
      if (!['all', 'file', 'directory'].includes(itemType)) throw new CloudDriveError('INVALID_ARGUMENT', 'item_type must be all, file, or directory')
      let modifiedAfter = null
      if (args.modified_after !== undefined) {
        modifiedAfter = new Date(requiredText(args.modified_after, 'modified_after'))
        if (Number.isNaN(modifiedAfter.valueOf())) throw new CloudDriveError('INVALID_ARGUMENT', 'modified_after must be an ISO-8601 timestamp')
      }
      const requestedLimit = positiveInteger(args.limit, 100, 'limit', 200)
      const response = expectStatus(await runCurl({
        account, signal: exec.signal, method: 'SEARCH', url: davRootUrl(account),
        headers: ['Content-Type: application/xml; charset=utf-8'],
        body: buildSearchBody(account, scopePath, query, 200), maxOutputBytes: config.maxMetadataBytes,
      }, config), [207], 'WebDAV SEARCH')
      let entries = parseDavResponses(account, response.body, 'files').map(publicEntry)
      if (itemType !== 'all') entries = entries.filter(item => item.type === itemType)
      if (modifiedAfter !== null) entries = entries.filter(item => item.modifiedAt !== null && new Date(item.modifiedAt) >= modifiedAfter)
      const page = paginate(entries, requestedLimit, args.cursor)
      return { query, scopePath, itemType, entries: page.items, nextCursor: page.nextCursor, total: page.total }
    },
  })

  const getShareTool = defineTool({
    name: 'cloud_get_share',
    description: 'Read the current details of one incoming or outgoing share by ID.',
    parameters: { share_id: { type: 'string', required: true } },
    output: jsonOutput('Cloud share'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      return getShare(accountFor(exec), config, exec.signal, requiredText(args.share_id, 'share_id'))
    },
  })

  const searchRecipients = defineTool({
    name: 'cloud_search_recipients',
    description: 'Search valid Cloud Drive share recipients before creating a share.',
    parameters: {
      query: { type: 'string', required: true },
      item_type: { type: 'string', description: 'Share item type; file (default) or folder.' },
      limit: { type: 'integer', description: 'Maximum results from 1 through 200. Defaults to 50.' },
    },
    output: jsonOutput('Cloud share recipients'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const query = requiredText(args.query, 'query')
      const itemType = args.item_type ?? 'file'
      if (!['file', 'folder'].includes(itemType)) throw new CloudDriveError('INVALID_ARGUMENT', 'item_type must be file or folder')
      const limit = positiveInteger(args.limit, 50, 'limit', 200)
      const search = encodeURIComponent(query)
      const data = await requestOcs(account, config, exec.signal, {
        path: `ocs/v2.php/apps/files_sharing/api/v1/sharees?format=json&search=${search}&itemType=${itemType}&perPage=${limit}`,
      })
      return { query, itemType, recipients: mapRecipients(data).slice(0, limit) }
    },
  })

  return [copy, search, getShareTool, searchRecipients]
}


  return { buildSearchBody, mapRecipients, createExtendedTools }
})()

export const buildSearchBody = createExtendedToolsModule.buildSearchBody
export const mapRecipients = createExtendedToolsModule.mapRecipients
export const createExtendedTools = createExtendedToolsModule.createExtendedTools

const createRecoveryToolsModule = (() => {

const objectOutput = (render: (value: any) => string) => ({
  schema: { type: 'json' as const },
  render: (_args: unknown, value: any) => [{ type: 'text' as const, text: render(value) }],
})
const jsonOutput = label => objectOutput(value => `${label}: ${JSON.stringify(value)}`)

function opaqueId(value, name) {
  const id = requiredText(String(value ?? ''), name)
  if (id.includes('/') || id.includes('\\') || id.includes('\0') || id === '.' || id === '..') {
    throw new CloudDriveError('INVALID_ARGUMENT', `${name} must be one opaque identifier without path separators`)
  }
  return id
}

function publicTrash(item) {
  return {
    trashId: item.id,
    name: item.originalName ?? item.name,
    originalLocation: item.originalLocation,
    type: item.type,
    size: item.size,
    deletedAt: item.deletedAt,
    etag: item.etag,
  }
}

function publicVersion(item, fileId) {
  return {
    fileId: String(fileId),
    versionId: item.id,
    size: item.size,
    modifiedAt: item.modifiedAt,
    etag: item.etag,
    label: item.versionLabel,
    author: item.versionAuthor,
  }
}

function createRecoveryTools(inputConfig = {}) {
  const config = runtimeConfig(inputConfig)

  const listTrash = defineTool({
    name: 'cloud_list_trash',
    description: 'List deleted Cloud Drive items that can be restored or permanently removed.',
    parameters: {
      limit: { type: 'integer', description: 'Maximum items from 1 through 200. Defaults to 100.' },
      cursor: { type: 'string' },
    },
    output: jsonOutput('Cloud trash'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const items = (await propfind(account, config, exec.signal, trashRootUrl(account), 1, 'trash'))
        .filter(item => item.id !== '')
        .map(publicTrash)
      const page = paginate(items, args.limit, args.cursor)
      return { items: page.items, nextCursor: page.nextCursor, total: page.total }
    },
  })

  const restoreTrash = defineTool({
    name: 'cloud_restore_trash',
    description: 'Restore one trash item to its original Cloud Drive location.',
    parameters: { trash_id: { type: 'string', required: true } },
    output: objectOutput(value => `Restored trash item ${value.trashId} to ${value.restoredPath}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const trashId = opaqueId(args.trash_id, 'trash_id')
      const items = await propfind(account, config, exec.signal, trashItemUrl(account, trashId), 0, 'trash')
      const item = items[0]
      if (item === undefined) throw new CloudDriveError('NOT_FOUND', `trash item ${trashId} was not found`)
      const response = expectStatus(await runCurl({
        account, signal: exec.signal, method: 'MOVE', url: trashItemUrl(account, trashId),
        headers: [`Destination: ${trashRestoreUrl(account)}/${encodeURIComponent(trashId)}`], maxOutputBytes: 64 * 1024,
      }, config), [201, 204], `restore trash item ${trashId}`)
      const original = item.originalLocation ?? item.originalName ?? item.name
      const restoredPath = normalizeRemotePath(`/${String(original).replace(/^\/+/, '')}`)
      const restored = await statRemote(account, config, exec.signal, restoredPath)
      return { trashId, restored: true, restoredPath, type: restored.type, etag: restored.etag, httpStatus: response.status }
    },
  })

  const deletePermanently = defineTool({
    name: 'cloud_delete_permanently',
    description: 'Permanently delete one item from Cloud Drive trash. This cannot be restored afterward.',
    parameters: { trash_id: { type: 'string', required: true } },
    output: objectOutput(value => `Permanently deleted trash item ${value.trashId}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const trashId = opaqueId(args.trash_id, 'trash_id')
      const response = expectStatus(await runCurl({
        account, signal: exec.signal, method: 'DELETE', url: trashItemUrl(account, trashId), maxOutputBytes: 64 * 1024,
      }, config), [204], `permanently delete trash item ${trashId}`)
      return { trashId, deletedPermanently: true, httpStatus: response.status }
    },
  })

  const listVersions = defineTool({
    name: 'cloud_list_versions',
    description: 'List recoverable historical versions of one Cloud Drive file.',
    parameters: {
      remote_path: { type: 'string', required: true },
      limit: { type: 'integer', description: 'Maximum versions from 1 through 200. Defaults to 100.' },
      cursor: { type: 'string' },
    },
    output: jsonOutput('Cloud file versions'),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const remotePath = normalizeRemotePath(args.remote_path)
      const current = await statRemote(account, config, exec.signal, remotePath)
      if (current.type !== 'file') throw new CloudDriveError('INVALID_ARGUMENT', 'remote_path must identify a file')
      if (!current.fileId) throw new CloudDriveError('INVALID_DAV_RESPONSE', `no file ID returned for ${remotePath}`)
      const serverVersions = (await propfind(account, config, exec.signal, versionsRootUrl(account, current.fileId), 1, 'versions'))
        .filter(item => item.id !== String(current.fileId) && item.id !== '')
        .map(item => ({ ...publicVersion(item, current.fileId), source: 'server' }))
      const managedVersions = (await listManagedVersions(config, account, remotePath))
        .map(item => ({
          fileId: String(current.fileId), versionId: item.versionId, size: item.size,
          modifiedAt: item.modifiedAt, etag: item.etag, label: null, author: null, source: 'managed',
        }))
      const versions = [...managedVersions, ...serverVersions]
        .sort((a, b) => String(b.modifiedAt ?? b.versionId).localeCompare(String(a.modifiedAt ?? a.versionId)))
      const page = paginate(versions, args.limit, args.cursor)
      return { remotePath, fileId: String(current.fileId), versions: page.items, nextCursor: page.nextCursor, total: page.total }
    },
  })

  const restoreVersion = defineTool({
    name: 'cloud_restore_version',
    description: 'Restore one historical version over the current Cloud Drive file.',
    parameters: {
      remote_path: { type: 'string', required: true },
      version_id: { type: 'string', required: true },
    },
    output: objectOutput(value => `Restored version ${value.versionId} of ${value.remotePath}.`),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      const account = accountFor(exec)
      const remotePath = normalizeRemotePath(args.remote_path)
      const versionId = opaqueId(args.version_id, 'version_id')
      const current = await statRemote(account, config, exec.signal, remotePath)
      if (current.type !== 'file' || !current.fileId) throw new CloudDriveError('INVALID_ARGUMENT', 'remote_path must identify a versioned file')
      let historicalBytes
      if (versionId.startsWith('dsh-')) {
        historicalBytes = (await readManagedVersion(config, account, remotePath, versionId)).bytes
      } else {
        const available = await propfind(account, config, exec.signal, versionsRootUrl(account, current.fileId), 1, 'versions')
        if (!available.some(item => item.id === versionId)) throw new CloudDriveError('VERSION_NOT_FOUND', `version ${versionId} does not belong to ${remotePath}`)
        const historical = expectStatus(await runCurl({
          account, signal: exec.signal, method: 'GET', url: versionItemUrl(account, current.fileId, versionId),
          maxOutputBytes: config.maxTransferBytes,
        }, config), [200], `read version ${versionId}`)
        historicalBytes = historical.body
      }
      const currentBytes = expectStatus(await runCurl({
        account, signal: exec.signal, method: 'GET', url: davUrl(account, remotePath), maxOutputBytes: config.maxTransferBytes,
      }, config), [200], `snapshot current ${remotePath}`)
      await saveManagedVersion(config, account, remotePath, currentBytes.body, current)
      const response = await runCurl({
        account, signal: exec.signal, method: 'PUT', url: davUrl(account, remotePath),
        headers: current.etag ? [`If-Match: ${current.etag}`] : [], body: historicalBytes, maxOutputBytes: 64 * 1024,
      }, config)
      if (response.status === 412) throw new CloudDriveError('PRECONDITION_FAILED', `${remotePath} changed while version ${versionId} was being restored`)
      expectStatus(response, [204], `restore version ${versionId}`)
      const restored = await statRemote(account, config, exec.signal, remotePath)
      return { remotePath, fileId: String(current.fileId), versionId, restored: true, etag: restored.etag, size: restored.size, httpStatus: response.status }
    },
  })

  return [listTrash, restoreTrash, deletePermanently, listVersions, restoreVersion]
}


  return { createRecoveryTools }
})()

export const createRecoveryTools = createRecoveryToolsModule.createRecoveryTools

export const name = 'emuvista-cloud-client'
export const inject = ['tools']

export function apply(ctx, config) {
  for (const tool of [...createCoreTools(config), ...createExtendedTools(config), ...createRecoveryTools(config)]) {
    ctx.tools.register(tool)
  }
}
