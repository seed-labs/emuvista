export type AttentionStatus = 'pending' | 'todo' | 'ignored' | 'done'

export interface CloudShareView {
  shareId: string
  path?: string
  name?: string
  ownerId?: string
  sharedBy?: string
  permissions?: unknown
  [key: string]: unknown
}

export interface AttentionItem {
  id: string
  kind: 'cloud-share' | 'cloud-file-change'
  observedAt: string
  status: AttentionStatus
  summary: string
  payload: CloudShareView
  deliveredMessageId?: string
  note?: string
}

export interface CloudWatch {
  shareId: string
  path: string
  direction: 'incoming' | 'outgoing'
  etag?: string
}

export interface AgentState {
  cloudBaselineEstablished: boolean
  seenCloudShareIds: string[]
  cloudWatches: CloudWatch[]
  attention: AttentionItem[]
  /** Identity of the DSH Schedule task that implements this Agent heartbeat. */
  heartbeatScheduleId?: string
}

export interface ClawState {
  version: 1
  agents: Record<string, AgentState>
}

export function emptyState(): ClawState {
  return { version: 1, agents: {} }
}

export function emptyAgentState(): AgentState {
  return {
    cloudBaselineEstablished: false,
    seenCloudShareIds: [],
    cloudWatches: [],
    attention: [],
  }
}

export function shareIdentity(share: CloudShareView): string {
  const id = String(share.shareId ?? '').trim()
  if (id === '') throw new Error('cloud_list_shares returned an incoming share without shareId')
  return id
}

export function discoverCloudShares(
  state: AgentState,
  shares: readonly CloudShareView[],
  now: string,
  maxSeen: number,
): AttentionItem[] {
  for (const share of shares) ensureCloudWatch(state, share)
  const currentIds = shares.map(shareIdentity)
  if (!state.cloudBaselineEstablished) {
    state.cloudBaselineEstablished = true
    state.seenCloudShareIds = currentIds.slice(-maxSeen)
    return []
  }

  const seen = new Set(state.seenCloudShareIds)
  const additions: AttentionItem[] = []
  for (const share of shares) {
    const shareId = shareIdentity(share)
    if (seen.has(shareId)) continue
    seen.add(shareId)
    const path = typeof share.path === 'string' ? share.path
      : typeof share.targetPath === 'string' ? share.targetPath
        : typeof share.sourcePath === 'string' ? share.sourcePath
          : typeof share.name === 'string' ? share.name : '(unknown path)'
    const actor = typeof share.sharedBy === 'string'
      ? share.sharedBy
      : typeof share.ownerId === 'string' ? share.ownerId : 'another account'
    additions.push({
      id: `cloud-share:${shareId}`,
      kind: 'cloud-share',
      observedAt: now,
      status: 'pending',
      summary: `${actor} shared ${path}`,
      payload: share,
    })
  }
  state.seenCloudShareIds = [...seen].slice(-maxSeen)
  const existing = new Set(state.attention.map(item => item.id))
  state.attention.push(...additions.filter(item => !existing.has(item.id)))
  return additions
}

export function ensureCloudWatch(state: AgentState, share: CloudShareView): CloudWatch | undefined {
  const shareId = shareIdentity(share)
  const direction = share.direction === 'outgoing' ? 'outgoing' : 'incoming'
  const candidate = direction === 'incoming' ? share.targetPath : share.sourcePath
  const path = typeof candidate === 'string' ? candidate.trim() : ''
  if (path === '') return undefined
  const existing = state.cloudWatches.find(watch => watch.shareId === shareId && watch.direction === direction)
  if (existing !== undefined) {
    existing.path = path
    return existing
  }
  const watch: CloudWatch = { shareId, path, direction }
  state.cloudWatches.push(watch)
  return watch
}

export function observeCloudEtag(
  state: AgentState,
  watch: CloudWatch,
  etag: string,
  now: string,
): AttentionItem | undefined {
  if (watch.etag === undefined) {
    watch.etag = etag
    return undefined
  }
  if (watch.etag === etag) return undefined
  const previousEtag = watch.etag
  watch.etag = etag
  const item: AttentionItem = {
    id: `cloud-file-change:${watch.shareId}:${etag}`,
    kind: 'cloud-file-change',
    observedAt: now,
    status: 'pending',
    summary: `${watch.path} changed`,
    payload: {
      shareId: watch.shareId,
      path: watch.path,
      direction: watch.direction,
      previousEtag,
      etag,
    },
  }
  if (!state.attention.some(existing => existing.id === item.id)) state.attention.push(item)
  return item
}
