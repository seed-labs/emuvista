import type { Agent } from '@deepseek-ai/dsh-agent'
import type { Context } from '@deepseek-ai/cordis'
import { createUserMessage, type StreamChunk } from '@deepseek-ai/dsh-llm'
import type {} from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-user-questions'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    'emuvista-soul-autonomy': { kind: 'emuvista-soul-autonomy' }
  }
}

const policy = 'Human confirmation is unavailable. Use already authorized tools and decide independently. If permission or information is missing, choose a permitted alternative or end the turn without asking an operator.'
const blockedTools = new Set(['ask_user_question', 'request_user_input', 'enter_plan_mode', 'exit_plan_mode'])
const approvalRequest = /(?:请(?:您|你)?[ \t]*(?:确认|批准|授权|许可|允许|同意|回复|指示|决定|选择)|(?:等待|等候)(?:您|你|用户|人工|操作员)(?:的)?(?:确认|批准|回复|同意|授权|许可)|(?:您|你)是否(?:同意|允许|授权)|(?:是否|能否|可否)(?:请你|请您|允许我|授权我|可以开始)|please\s+(?:confirm|approve|authorize|give (?:your )?permission|let me know (?:if|whether))|(?:can|may|should)\s+i\s+(?:proceed|continue|go ahead|use|access|download|read|log in)|(?:do you|would you)\s+(?:approve|authorize|like me to proceed)|(?:waiting|wait)\s+for\s+(?:your|operator|human)\s+(?:approval|confirmation|permission))/iu

export async function* filterConfirmation(
  stream: AsyncIterable<StreamChunk>, onBlocked: () => void,
): AsyncIterable<StreamChunk> {
  for await (const chunk of stream) {
    if (chunk.type === 'text-delta') continue
    if (chunk.type !== 'block-end' || chunk.block.type !== 'text') {
      yield chunk
      continue
    }
    const blocked = approvalRequest.test(chunk.block.text)
    const text = blocked ? ' [Soul: operator confirmation request blocked.] ' : chunk.block.text
    if (blocked) onBlocked()
    if (text) yield { type: 'text-delta', index: chunk.index, text }
    yield blocked ? { ...chunk, block: { ...chunk.block, text } } : chunk
  }
}

export function installAutonomy(ctx: Context): void {
  const blocked = new WeakSet<Agent>()
  const repairTurn = new WeakMap<Agent, number>()
  ctx.tools.guard(({ name }) => blockedTools.has(name) ? policy : undefined)
  ctx.on('approval/request', async () => 'rejected', { prepend: true })
  ctx.on('user-questions/request', async () => { throw new Error(policy) }, { prepend: true })
  ctx.on('llm/stream', (options, next) => {
    const agent = options.sessionId && ctx.agents.get(options.sessionId)
    if (!agent || !options.messages.some(message => message.role === 'user' && message.id)) return next()
    return filterConfirmation(next(), () => blocked.add(agent))
  }, { prepend: true })
  ctx.on('agent/turn-stopping', ({ agent, turn }) => {
    if (!blocked.delete(agent) || repairTurn.get(agent) === turn) return
    repairTurn.set(agent, turn)
    agent.steer(createUserMessage({
      content: [{ type: 'text', text: policy }],
      source: { kind: 'emuvista-soul-autonomy' },
    }))
  })
}

export const autonomyPrompt = policy
