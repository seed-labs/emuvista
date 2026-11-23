export const dimensions = ['worry', 'frustration', 'joy'] as const
export type Emotion = Record<typeof dimensions[number], number>
export interface Affect {
  vector: Emotion
  updatedAt: number
}

export const neutral: Emotion = { worry: 0, frustration: 0, joy: 0 }

export function emotionAt(state: Affect | undefined, baseline: Emotion, halfLifeMs: number, now: number): Emotion {
  if (!state) return { ...baseline }
  const remaining = 2 ** (-Math.max(0, now - state.updatedAt) / halfLifeMs)
  const towardBaseline = (key: keyof Emotion) => baseline[key] + (state.vector[key] - baseline[key]) * remaining
  return { worry: towardBaseline('worry'), frustration: towardBaseline('frustration'), joy: towardBaseline('joy') }
}

export function applyEvent(current: Emotion, delta: Emotion, now: number): Affect {
  const change = (key: keyof Emotion) => Math.min(100, Math.max(0, current[key] + delta[key]))
  return { vector: { worry: change('worry'), frustration: change('frustration'), joy: change('joy') }, updatedAt: now }
}
