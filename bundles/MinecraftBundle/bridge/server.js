// 提供容器内 HTTP 接口，并为移动任务生成唯一 ID。
'use strict'
const { createToolApi, serve } = require('./tool_api')
const { landmarks } = require('./navigation')
const { randomUUID } = require('node:crypto')
const { itemDefinition: registryItem } = require('./item_registry')
// 通过依赖注入创建桥接对象，便于测试时替换 Mineflayer；连接、聊天和任务状态在闭包内共享。
function createBridge ({ createBot, pathfinder, Movements, GoalNear, GoalFollow, options, chatRadius = 32, allowPathfinderDig = true }) {
  if (!Number.isFinite(chatRadius) || chatRadius < 0) throw new Error('MC_CHAT_RADIUS must be a finite nonnegative number')
  let bot, connected = false, lastError = null, closing = false, retry, active = null
  let pendingInventory = null
  let chatId = 0
  const messages = [], events = [], jobs = new Map()
  // A new bridge instance gets a new epoch so consumers can detect reset notification IDs.
  const notificationEpoch = randomUUID()
  const notifications = []
  let notificationId = 0
  let eventId = 0
  /**
   * Cache a bridge event and, for selected types, enqueue an agent notification.
   * Both buffers are in memory and retain only their latest 100 entries; reads do
   * not consume them. Event IDs and notification IDs are independent sequences.
   * Event details are flattened into the event record but nested under `data` in
   * notifications. Timestamps are wall-clock UTC; game time belongs in details.
   * This only queues data: the adapter polls /notifications before model calls.
   * @param {string} type Event category, such as chat, time, or action_finished.
   * @param {object} details Observed event fields; do not override id, timestamp, or type.
   */
  function record (type, details = {}) {
    events.push({ id: ++eventId, timestamp: new Date().toISOString(), type, ...details })
    if (events.length > 100) events.shift()
    // Only these events enter the automatic model feed. Other events remain in events.
    if (['chat', 'hurt', 'death', 'spawn', 'disconnected', 'time'].includes(type)) {
      // Urgency controls delivery order in the adapter, not interruption of a running action.
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
    // Diagnostic event only; consumers must inspect the job for results and pending effects.
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
    return registryItem(bot.registry, name)
  }
  function inventoryItem (name) {
    const definition = itemDefinition(name)
    const item = bot.inventory.items().find(i => i.name === definition.name)
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
      // Experiments may disable implicit digging without changing explicit dig tools.
      bot.on('spawn', () => {
        const movements = new Movements(bot)
        if (!allowPathfinderDig) {
          movements.canDig = false
          movements.allow1by1towers = false
          movements.scafoldingBlocks = []
        }
        bot.pathfinder.setMovements(movements)
        connected = true
        // Snapshot the spawn position; later movement must not mutate this event.
        record('spawn', { position: bot.entity.position.clone() })
        lastError = null
        console.log(`${bot.username} joined Minecraft Java 26.1`)
      })
      // Use server time packets, not a wall-clock timer. First packet establishes
      // the baseline; jumps report only the latest hour, never a backlog.
      const actor = bot
      let lastTimeHour = null
      actor.on('time', () => {
        if (actor !== bot || !connected) return
        const ticks = actor.time?.timeOfDay
        const day = actor.time?.day
        const dimension = actor.game?.dimension
        if (!Number.isFinite(ticks) || ticks < 0 || ticks >= 24000 ||
            !Number.isSafeInteger(day) || day < 0 || !dimension) return
        const hourKey = `${dimension}:${day}:${Math.floor(ticks / 1000)}`
        const previous = lastTimeHour
        lastTimeHour = hourKey
        if (previous === null || previous === hourKey) return
        const minutes = (Math.floor(ticks * 60 / 1000) + 360) % 1440
        // Publish the zero-based world day and current clock, not elapsed agent runtime.
        record('time', {
          day, time_of_day: ticks,
          clock_24h: `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`,
          dimension,
          source: 'latest server time received by Mineflayer',
          clock_basis: '24000 ticks per game day; tick 0 = 06:00; day is zero-based; not real-world time'
        })
      })
      // Keep the latest 100 chat messages separately, including the bot's own messages.
      // Only nearby messages from other players become automatic notifications.
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
      // Self-injury is urgent; injury to another entity is only a diagnostic event.
      // The event does not identify an attacker or cause; health is the last known value.
      bot.on('entityHurt', entity => {
        if (entity === bot.entity) record('hurt', { last_known_health: bot.health, attacker: null, cause: 'unknown' })
        else record('entity_hurt', { entity_id: entity.id, name: entity.username || entity.name, attribution: 'unknown' })
      })
      // Record collector/entity identity only: this does not establish item type or quantity.
      // Collection events are not included in the automatic notification feed.
      bot.on('playerCollect', (collector, collected) => {
        record('item_collected', { collector_id: collector.id, collector: collector.username || collector.name,
          collected_entity_id: collected.id })
      })
      // Weather changes are cached events, not automatic agent notifications.
      bot.on('rain', () => record('weather_changed', { raining: bot.isRaining }))
      // Queue an urgent death notice, stop navigation, and fail the active action.
      // A later spawn event restores readiness independently of model processing.
      bot.on('death', () => {
        connected = false
        record('death')
        bot.pathfinder.setGoal(null)
        finish('failed', 'Player died')
      })
      // Cache the latest error/kick reason for the eventual disconnect notification.
      // On disconnect, fail the active action and reconnect unless shutdown was requested.
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
  // 读取 32 格内最近 20 个实体（含掉落物详情）及最多 256 个已加载的非空气方块；不检查视线遮挡。
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
      point: position, maxDistance: 32, count: 256
    }).map(p => bot.blockAt(p)).filter(block => block && block.position.distanceTo(position) <= 32)
      .map(block => ({ name: block.name, position: block.position, distance: block.position.distanceTo(position) }))
      .sort((a, b) => a.distance - b.distance)
    return { connected: true, version: '26.1', username: bot.username, position,
      health: bot.health, food: bot.food, is_sleeping: bot.isSleeping,
      game_mode: bot.game?.gameMode ?? null,
      time_of_day: bot.time?.timeOfDay, raining: bot.isRaining, dimension: bot.game?.dimension,
      yaw: bot.entity.yaw, pitch: bot.entity.pitch,
      held_item: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null,
      block_below: bot.blockAt(position.offset(0, -1, 0))?.name || null,
      inventory: bot.inventory.items().map(i => ({ name: i.name, count: i.count })),
      nearby_entities: nearby, nearby_blocks: nearbyBlocks,
      navigation_landmarks: landmarks(bot),
      observation_scope: 'nearest 20 client-known entities and up to 256 nearest loaded non-air blocks within 32 blocks; not line-of-sight filtered; blocks are a limited sample, not a complete terrain map; dropped_item is null for non-items or unavailable item metadata',
      active_action: active ? active.job : null }
  }
  // 按方法和路径分派请求；状态、聊天历史、任务查询和取消操作在离线时也可调用。
  const dispatch = createToolApi({
    get bot () { return bot }, get connected () { return connected },
    get pendingInventory () { return pendingInventory }, get chatId () { return chatId },
    get active () { return active }, set active (value) { active = value }
  }, { messages, notifications, notificationEpoch, jobs, ready, observe, finish, inventoryAction,
    inventoryItem, inventorySnapshot, itemDefinition, nearbyTable, recipeKey,
    GoalNear, GoalFollow })
  // 主动关闭时取消重连和任务计时器，再退出游戏，避免退出事件触发重连。
  function close () {
    closing = true
    clearTimeout(retry)
    const digging = active?.job.kind === 'dig_blocks'
    finish('cancelled', 'Bridge stopping')
    if (digging) bot.stopDigging()
    if (bot) { bot.pathfinder.setGoal(null); bot.quit() }
  }
  return { connect, dispatch, close }
}

// 直接运行时加载真实依赖和环境配置，固定 MC Java 26.1；被测试导入时不自动联网。
if (require.main === module) {
  const identity = process.env.MC_AGENT_NAME
  if (!identity) throw new Error('MC_AGENT_NAME is required')
  const prefix = 'MC_' + identity.toUpperCase() + '_'
  const username = process.env[prefix + 'USERNAME']?.trim()
  if (!username) throw new Error(`Set ${prefix}USERNAME in the experiment .env`)
  const mineflayer = require('mineflayer')
  const { pathfinder, Movements, goals: { GoalNear, GoalFollow } } = require('mineflayer-pathfinder')
  console.log('Minecraft navigation engine: mineflayer-pathfinder')
  const bridge = createBridge({ createBot: mineflayer.createBot, pathfinder, Movements, GoalNear, GoalFollow,
    chatRadius: Number(process.env.MC_CHAT_RADIUS ?? 32),
    allowPathfinderDig: process.env.MC_PATHFINDER_CAN_DIG !== 'false',
    options: { host: process.env.MC_HOST || 'minecraft', port: Number(process.env.MC_PORT),
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
module.exports = { createBridge, serve }
