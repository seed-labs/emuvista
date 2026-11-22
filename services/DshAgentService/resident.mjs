// A child fiber owns each resident plugin's tools and other registrations.
export const inject = ['agents']

export async function mount(ctx, module, config) {
  const plugin = typeof module.apply === 'function' ? module : module.default
  const mounted = new Map()

  function attach(agent) {
    if (mounted.has(agent) || !ctx.agents.roots().includes(agent)) return
    const fiber = agent.ctx.plugin(plugin, config)
    const dispose = ctx.effect(() => () => fiber.dispose())
    mounted.set(agent, dispose)
    return fiber.await()
  }

  ctx.on('agent/created', ({ agent }) => {
    // Cordis logs activation failures on the child fiber.
    void attach(agent)?.catch(() => {})
  })
  ctx.on('agent/disposed', ({ agent }) => {
    const dispose = mounted.get(agent)
    mounted.delete(agent)
    if (dispose) void dispose()
  })
  await Promise.all(ctx.agents.roots().map(attach))
}
