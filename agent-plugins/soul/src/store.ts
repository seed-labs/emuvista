import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import type { Affect, Emotion } from './emotion.js'

export type EntryKind = 'experience' | 'relationship' | 'reflection'
export interface Entry {
  id: string
  kind: EntryKind
  text: string
  at: string
  sessionId: string
  about?: string
  certainty?: 'observed' | 'inferred'
  source?: string
  evidence?: string[]
  emotionChange?: Emotion
  concernRevision?: {
    intentionId: string
    action: 'update' | 'shelve' | 'restore'
    before: { wish: string; weight: number; shelved: boolean }
    after: { wish: string; weight: number; shelved: boolean }
  }
}
export type Status = 'candidate' | 'active' | 'paused' | 'completed' | 'abandoned'
export interface Intention {
  id: string
  wish: string
  weight?: number
  reflectionId: string
  latestReflectionId?: string
  shelved?: boolean
  status: Status
  reason: string
  completion?: string
  updatedAt: string
}
export interface Rest {
  intentionId: string
  sessionId: string
  title: string
  question: string
  scheduleId?: string
  scheduledAt?: string
}
export interface Life {
  sessionId: string
  title: string
  intervalSeconds: number
}

export interface State {
  version: 1
  concernWeightScale?: 100
  residentId: string
  entries: Entry[]
  intentions: Intention[]
  lastAutoReflectionMemoryId?: string
  concernReviews?: Record<string, { firstAt: number; lastAt: number }>
  affect?: Affect
  rest?: Rest
  life?: Life
}

export function text(value: unknown, label: string, max = 1200): string {
  if (typeof value !== 'string' || !value.trim() || [...value.trim()].length > max) {
    throw new Error(`${label} must contain 1–${max} characters`)
  }
  return value.trim()
}

export function transition(current: Intention, status: Status, reason: string, completion?: string): Intention {
  const allowed: Record<Status, readonly Status[]> = {
    candidate: ['active', 'abandoned'],
    active: ['active', 'paused', 'completed', 'abandoned'],
    paused: ['active', 'paused', 'completed', 'abandoned'],
    completed: [],
    abandoned: [],
  }
  if (!allowed[current.status].includes(status)) throw new Error('Invalid intention transition')
  const condition = completion ?? current.completion
  if (status === 'active' && !condition) throw new Error('An active intention requires a completion condition')
  return { ...current, status, reason, ...(condition ? { completion: condition } : {}), updatedAt: new Date().toISOString() }
}

export class SoulStore {
  private chain: Promise<unknown> = Promise.resolve()
  private current: State
  readonly ready: Promise<void>

  constructor(private readonly path: string, residentId: string) {
    this.current = { version: 1, concernWeightScale: 100, residentId, entries: [], intentions: [] }
    this.ready = this.load()
  }

  snapshot(): State {
    return structuredClone(this.current)
  }

  private async load(): Promise<void> {
    try {
      const state = JSON.parse(await readFile(this.path, 'utf8')) as State
      if (state.version !== 1 || state.residentId !== this.current.residentId ||
          !Array.isArray(state.entries) || !Array.isArray(state.intentions)) {
        throw new Error('Soul state does not match the configured resident or format')
      }
      if (state.concernWeightScale === undefined) {
        for (const intention of state.intentions) {
          if (intention.weight !== undefined) intention.weight = (intention.weight - 1) * 25
        }
        state.concernWeightScale = 100
      }
      this.current = state
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    }
  }

  run<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.chain.then(async () => {
      await this.ready
      return operation()
    })
    this.chain = result.catch(() => undefined)
    return result
  }

  async save(next: State): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 })
    const temporary = `${this.path}.${randomUUID()}.tmp`
    try {
      await writeFile(temporary, JSON.stringify(next, null, 2) + '\n', { mode: 0o600, flag: 'wx' })
      await rename(temporary, this.path)
      this.current = next
    } finally {
      await rm(temporary, { force: true })
    }
  }
}
