// 提供容器内 HTTP 接口，并为移动任务生成唯一 ID。
'use strict'
const { createToolApi, serve } = require('./tool_api')
const { randomUUID } = require('node:crypto')
// One shared approach-and-swing primitive; the caller owns cancellation and limits.
async function attackOnce (bot, target, check, { GoalFollow, ended, job }) {
  check()
  let following = false
  while (true) {
    check()
    const reason = ended()
    if (reason) return reason
    if (bot.entity.position.distanceTo(target.position) <= 2.5) {
      bot.pathfinder.setGoal(null)
      following = false
      job.phase = 'aiming'
      await bot.lookAt(target.position.offset(0, (target.height || 1) * 0.8, 0), true)
      check()
      const reasonAfterLook = ended()
      if (reasonAfterLook) return reasonAfterLook
      if (bot.entity.position.distanceTo(target.position) <= 2.5) {
        job.phase = 'attacking'
        bot.attack(target)
        job.attacks_submitted++
        return 'attack_submitted'
      }
    }
    job.phase = 'approaching'
    if (!following) {
      bot.pathfinder.setGoal(new GoalFollow(target, 1), true)
      following = true
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
}

// Observe protocol updates, not blockUpdate events: digging also emits those locally.
// A received update establishes server state, not which player caused the change.
function watchServerBlock (bot, position) {
  let observed = null
  const record = (p, stateId) => {
    if (p.x !== position.x || p.y !== position.y || p.z !== position.z) return
    const definition = bot.registry.blocksArray.find(b => stateId >= b.minStateId && stateId <= b.maxStateId)
    observed = { state_id: stateId, name: definition?.name ?? null }
  }
  const single = packet => record(packet.location, packet.type)
  const multiple = packet => {
    const packed = bot.supportFeature('usesMultiblockSingleLong')
    const chunk = bot.supportFeature('usesMultiblock3DChunkCoords')
      ? packet.chunkCoordinates : { x: packet.chunkX, y: 0, z: packet.chunkZ }
    for (const entry of packet.records) {
      const x = packed ? (entry >> 8) & 15 : (entry.horizontalPos >> 4) & 15
      const y = packed ? entry & 15 : entry.y
      const z = packed ? (entry >> 4) & 15 : entry.horizontalPos & 15
      record({ x: chunk.x * 16 + x, y: chunk.y * 16 + y, z: chunk.z * 16 + z },
        packed ? entry >> 12 : entry.blockId)
    }
  }
  bot._client.on('block_change', single)
  bot._client.on('multi_block_change', multiple)
  return {
    async wait (accept, alive) {
      const deadline = Date.now() + 1500
      while (alive() && Date.now() < deadline) {
        if (observed && accept(observed.name)) return observed
        await new Promise(resolve => setTimeout(resolve, 50))
      }
      return observed
    },
    close () {
      bot._client.removeListener('block_change', single)
      bot._client.removeListener('multi_block_change', multiple)
    }
  }
}

// Execute in supplied order without automatic navigation, equipment selection or retries.
async function digBatch ({ bot, targets, job, alive }) {
  for (let index = 0; index < targets.length; index++) {
    if (!alive()) return
    const target = targets[index]
    job.target = target.position
    job.phase = 'digging'
    const block = bot.blockAt(target.position)
    try {
      if (!block) throw new Error('Requested block is not loaded')
      job.block = block.name
      if (['air', 'cave_air', 'void_air'].includes(block.name)) {
        job.skipped_blocks.push({ position: target.position, reason: 'client_known_air', server_removal_verified: false })
        job.remaining_blocks = targets.slice(index + 1).map(t => t.position)
        continue
      }
      if (!bot.canDigBlock(block)) throw new Error('Block is out of digging reach or not diggable; move closer and observe before retrying')
      const update = watchServerBlock(bot, target.position)
      try {
        await bot.dig(block)
        if (!alive()) return
        job.phase = 'confirming'
        const isAir = name => ['air', 'cave_air', 'void_air'].includes(name)
        const observed = await update.wait(isAir, alive)
        if (!alive()) return
        if (!observed || !isAir(observed.name)) {
          job.outcome_unknown = true
          job.unverified_blocks.push({ position: target.position, observed_server_block: observed,
            completion_basis: 'mineflayer_promise_resolved', server_removal_verified: false })
          throw new Error('Digging not confirmed by server: ' + (observed ? `received ${observed.name ?? observed.state_id}` : 'no target block update received') + '; do not treat client-known air as proof of removal')
        }
      } finally {
        update.close()
      }
    } catch (error) {
      if (!alive()) return
      job.failed_blocks.push({ position: target.position, reason: error.message })
      throw error
    }
    if (!alive()) return
    job.completed_blocks.push({ position: target.position, block: block.name,
      completion_basis: 'server_block_update_to_air', server_removal_verified: true })
    job.remaining_blocks = targets.slice(index + 1).map(t => t.position)
  }
}

// 通过依赖注入创建桥接对象，便于测试时替换 Mineflayer；连接、聊天和任务状态在闭包内共享。
function createBridge ({ createBot, pathfinder, Movements, GoalNear, GoalFollow, options, chatRadius = 32 }) {
  if (!Number.isFinite(chatRadius) || chatRadius < 0) throw new Error('MC_CHAT_RADIUS must be a finite nonnegative number')
  let bot, connected = false, lastError = null, closing = false, retry, active = null
  let pendingInventory = null
  let chatId = 0
  const messages = [], events = [], jobs = new Map()
  const notificationEpoch = randomUUID()
  const notifications = []
  let notificationId = 0
  let eventId = 0
  function record (type, details = {}) {
    events.push({ id: ++eventId, timestamp: new Date().toISOString(), type, ...details })
    if (events.length > 100) events.shift()
    if (['chat', 'hurt', 'death', 'spawn', 'disconnected'].includes(type)) {
      notifications.push({ id: ++notificationId, type, timestamp: new Date().toISOString(),
        priority: ['hurt', 'death', 'disconnected'].includes(type) ? 'urgent' : 'normal', data: details })
      if (notifications.length > 100) notifications.shift()
    }
  }
  // 结束当前任务并保留历史记录；这里只更新状态，停止寻路需另行调用 setGoal(null)。
  function finish (state, error) {
    if (!active) return
    if (['attack', 'hunt_entity'].includes(active.job.kind) && !active.job.end_reason) active.job.end_reason = state
    if (active.cleanup) active.cleanup()
    if (active.job.kind === 'dig_blocks') bot.pathfinder.setGoal(null)
    clearTimeout(active.timer)
    active.job.status = state
    if (error) active.job.error = String(error).slice(0, 300)
    record('action_finished', { action_id: active.job.id, status: state, error: active.job.error })
    active = null
  }
  // Native asynchronous operations cannot always be safely undone mid-packet. Keep the shared action
  // slot locked until their promise settles, even after an application timeout.
  function inventoryAction (kind, details, run, seconds = 30) {
    if (active || pendingInventory) throw new Error('An action is running; wait for its result')
    const actor = bot
    const job = { id: randomUUID(), kind, status: 'running', cancellable: false, ...details }
    jobs.set(job.id, job)
    if (jobs.size > 100) jobs.delete(jobs.keys().next().value)
    pendingInventory = job
    const timer = setTimeout(() => {
      if (active?.job !== job) return
      job.outcome_unknown = true
      job.pending = true
      finish('failed', 'Operation timed out; wait for pending=false and inspect inventory/world before retrying')
    }, seconds * 1000)
    active = { job, timer }
    const check = () => {
      if (!connected || bot !== actor || active?.job !== job) throw new Error('Action no longer active')
    }
    Promise.resolve().then(() => { check(); return run(actor, check, job) }).then(result => {
      if (active?.job === job) {
        job.result = result
        finish('completed')
      } else job.late_result = result
    }).catch(error => {
      if (active?.job === job) {
        job.outcome_unknown = true
        finish('failed', error.message)
      } else job.late_error = String(error.message).slice(0, 300)
    }).finally(() => {
      job.pending = false
      if (pendingInventory === job) pendingInventory = null
    })
    return { ...job }
  }
  function itemDefinition (name) {
    if (typeof name !== 'string' || !/^[a-z0-9_]{1,100}$/.test(name) || !bot.registry.itemsByName[name]) {
      throw new Error('Unknown item name; use a registry name such as oak_planks')
    }
    return bot.registry.itemsByName[name]
  }
  function inventoryItem (name) {
    itemDefinition(name)
    const item = bot.inventory.items().find(i => i.name === name)
    if (!item) throw new Error('Item is not in inventory')
    return item
  }
  function inventorySnapshot (actor) {
    return actor.inventory.items().map(i => ({ name: i.name, count: i.count }))
  }
  function nearbyTable () {
    const id = bot.registry.blocksByName.crafting_table?.id
    if (id === undefined) return null
    // matching also runs on palette samples, whose position is null.
    // useExtraInfo runs only on actual world blocks with coordinates.
    return bot.findBlock({ matching: id, maxDistance: 4,
      useExtraInfo: b => Boolean(b?.position) })
  }
  function recipeKey (recipe) { return JSON.stringify(recipe) }
  // 创建机器人并加载寻路插件；连接失败或断开后每隔 5 秒重连，不重放之前的动作。
  function connect () {
    if (closing) return
    try {
      bot = createBot(options)
      bot.loadPlugin(pathfinder)
      // Use the dependency's default movement policy without project overrides.
      bot.on('spawn', () => {
        bot.pathfinder.setMovements(new Movements(bot))
        connected = true
        record('spawn', { position: bot.entity.position.clone() })
        lastError = null
        console.log(`${bot.username} joined Minecraft Java 26.1`)
      })
      // 缓存最近 100 条聊天，使用递增游标支持增量读取；重建 bridge 后缓存和游标重置。
      bot.on('chat', (username, message) => {
        messages.push({ id: ++chatId, username, message, self: username === bot.username })
        if (messages.length > 100) messages.shift()
        if (username === bot.username) return
        const sender = bot.players?.[username]?.entity || Object.values(bot.entities).find(e => e.username === username)
        const distance = sender?.position && bot.entity?.position
          ? sender.position.distanceTo(bot.entity.position) : NaN
        // Unknown positions cannot establish audibility. Radius is checked at receipt, not delivery.
        if (Number.isFinite(distance) && distance <= chatRadius) {
          record('chat', { username, message, distance, radius: chatRadius })
        }
      })
      // 记录客户端实际收到的事件；拾取事件仅确认实体拾取，不推断物品名称或数量。
      bot.on('entityHurt', entity => {
        if (entity === bot.entity) record('hurt', { last_known_health: bot.health, attacker: null, cause: 'unknown' })
        else record('entity_hurt', { entity_id: entity.id, name: entity.username || entity.name, attribution: 'unknown' })
      })
      bot.on('playerCollect', (collector, collected) => {
        record('item_collected', { collector_id: collector.id, collector: collector.username || collector.name,
          collected_entity_id: collected.id })
      })
      bot.on('rain', () => record('weather_changed', { raining: bot.isRaining }))
      // 死亡时暂停操作并将当前任务标为失败，等待后续出生事件恢复。
      bot.on('death', () => {
        connected = false
        record('death')
        bot.pathfinder.setGoal(null)
        finish('failed', 'Player died')
      })
      // 记录连接错误和被踢原因；连接结束时让当前任务失败，并在非主动关闭时安排重连。
      bot.on('error', error => { lastError = error.message; console.error('MC error:', error.message) })
      bot.on('kicked', reason => { lastError = typeof reason === 'string' ? reason : JSON.stringify(reason) })
      bot.on('end', () => {
        connected = false
        pendingInventory = null
        record('disconnected', { error: lastError })
        finish('failed', 'Disconnected; inspect state before retrying')
        if (!closing) retry = setTimeout(connect, 5000)
      })
    } catch (error) {
      lastError = error.message
      if (!closing) retry = setTimeout(connect, 5000)
    }
  }
  // 聊天发送和移动要求角色已出生且可操作；仅建立网络连接还不够。
  function ready () {
    if (!connected) throw new Error('Minecraft is not connected: ' + (lastError || 'joining'))
  }
  // 读取 32 格内最近 20 个实体（含掉落物详情）及最多 64 个已加载的非空气方块；不检查视线遮挡。
  function observe () {
    if (!connected) return { connected: false, version: '26.1', error: lastError }
    const position = bot.entity.position
    const nearby = Object.values(bot.entities).filter(e => e !== bot.entity && e.position.distanceTo(position) <= 32)
      .sort((a, b) => a.position.distanceTo(position) - b.position.distanceTo(position)).slice(0, 20)
      .map(e => {
        const item = e.getDroppedItem()
        return { id: e.id, name: e.username || e.name, position: e.position,
          dropped_item: item ? { name: item.name, count: item.count } : null }
      })
    // Use native loaded-world lookup. This bounded sample is not a complete terrain map.
    const nearbyBlocks = bot.findBlocks({
      matching: block => !['air', 'cave_air', 'void_air'].includes(block.name),
      point: position, maxDistance: 32, count: 64
    }).map(p => bot.blockAt(p)).filter(block => block && block.position.distanceTo(position) <= 32)
      .map(block => ({ name: block.name, position: block.position, distance: block.position.distanceTo(position) }))
      .sort((a, b) => a.distance - b.distance)
    return { connected: true, version: '26.1', username: bot.username, position,
      health: bot.health, food: bot.food, is_sleeping: bot.isSleeping,
      time_of_day: bot.time?.timeOfDay, raining: bot.isRaining, dimension: bot.game?.dimension,
      yaw: bot.entity.yaw, pitch: bot.entity.pitch,
      held_item: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null,
      block_below: bot.blockAt(position.offset(0, -1, 0))?.name || null,
      inventory: bot.inventory.items().map(i => ({ name: i.name, count: i.count })),
      nearby_entities: nearby, nearby_blocks: nearbyBlocks,
      observation_scope: 'nearest 20 client-known entities and up to 64 nearest loaded non-air blocks within 32 blocks; not line-of-sight filtered; blocks are a limited sample, not a complete terrain map; dropped_item is null for non-items or unavailable item metadata',
      active_action: active ? active.job : null }
  }
  // 按方法和路径分派请求；状态、聊天历史、任务查询和取消操作在离线时也可调用。
  const dispatch = createToolApi({
    get bot () { return bot }, get connected () { return connected },
    get pendingInventory () { return pendingInventory }, get chatId () { return chatId },
    get active () { return active }, set active (value) { active = value }
  }, { messages, notifications, notificationEpoch, jobs, ready, observe, finish, inventoryAction,
    inventoryItem, inventorySnapshot, itemDefinition, nearbyTable, recipeKey, attackOnce, digBatch,
    GoalNear, GoalFollow, watchServerBlock })
  // 主动关闭时取消重连和任务计时器，再退出游戏，避免退出事件触发重连。
  function close () {
    closing = true
    clearTimeout(retry)
    const digging = active?.job.kind === 'dig_blocks'
    finish('cancelled', 'Bridge stopping')
    if (digging) bot.stopDigging()
    if (bot) bot.quit()
  }
  return { connect, dispatch, close }
}

// 直接运行时加载真实依赖和环境配置，固定 MC Java 26.1；被测试导入时不自动联网。
if (require.main === module) {
  const identity = process.env.E16_AGENT_NAME
  if (!identity) throw new Error('E16_AGENT_NAME is required')
  const prefix = 'MC_' + identity.toUpperCase() + '_'
  const username = process.env[prefix + 'USERNAME']?.trim()
  if (!username) throw new Error(`Set ${prefix}USERNAME in E16 .env`)
  const mineflayer = require('mineflayer')
  const { pathfinder, Movements, goals: { GoalNear, GoalFollow } } = require('mineflayer-pathfinder')
  const bridge = createBridge({ createBot: mineflayer.createBot, pathfinder, Movements, GoalNear, GoalFollow,
    chatRadius: Number(process.env.MC_CHAT_RADIUS ?? 32),
    options: { host: process.env.MC_HOST || 'host.docker.internal', port: Number(process.env.MC_PORT),
      username, auth: process.env[prefix + 'AUTH'] || process.env.MC_AUTH || 'offline',
      version: '26.1', profilesFolder: '/home/emuvista-agent/minecraft-auth' } })
  const server = serve(bridge)
  bridge.connect()
  // 响应进程终止信号，先断开机器人，再关闭 HTTP 服务并退出。
  const stop = () => { bridge.close(); server.close(() => process.exit(0)) }
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
}
// 导出工厂和 HTTP 服务入口供测试及其他模块复用。
module.exports = { createBridge, serve, attackOnce, digBatch }
