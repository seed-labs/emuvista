'use strict'
const http = require('node:http')
const { normalizeItemName, searchItems } = require('./item_registry')
const { categories, blockInfo, landmarks, openDoor } = require('./navigation')
const { randomUUID } = require('node:crypto')

const FACES = { up: [0, 1, 0], down: [0, -1, 0], north: [0, 0, -1], south: [0, 0, 1], east: [1, 0, 0], west: [-1, 0, 0] }

function furnaceWindow (bot) {
  const w = bot.currentWindow
  if (!w || typeof w.inputItem !== 'function' || typeof w.putFuel !== 'function') {
    throw new Error('Use open_furnace first; a generic container window is not sufficient')
  }
  return w
}

function furnaceInfo (bot) {
  const w = furnaceWindow(bot)
  const item = i => i ? { name: i.name, type: i.type, count: i.count, slot: i.slot } : null
  const number = n => Number.isFinite(n) ? n : null
  return { id: w.id, type: w.type, input: item(w.inputItem()), fuel_item: item(w.fuelItem()),
    output: item(w.outputItem()), fuel_fraction: number(w.fuel), progress_fraction: number(w.progress),
    fuel_seconds: number(w.fuelSeconds), remaining_seconds: number(w.progressSeconds),
    player_inventory: w.slots.slice(w.inventoryStart, w.inventoryEnd).filter(Boolean).map(item),
    observation_scope: 'client-known window; null progress means unknown; output may change concurrently' }
}

// Project policy: do not submit digging in protected/adventure mode, even
// when a special item could allow it. Recheck before each block in a batch.
function requireDiggingMode (bot) {
  const mode = bot.game?.gameMode
  if (!['survival', 'creative'].includes(mode)) {
    throw new Error(`Digging blocked in game mode ${mode ?? 'unknown'}. Adventure mode may mark a protected residential area. Do not retry digging here or change game mode; leave the protected area, observe again, and harvest only verified natural trees.`)
  }
}

// Public native methods only. JSON references are converted to live objects; no eval
// or arbitrary bot/private-property lookup is exposed.
function nativeMethods (bot) {
  const vector = p => {
    if (!p || !['x', 'y', 'z'].every(k => typeof p[k] === 'number' && Number.isFinite(p[k]))) throw new Error('Expected {x,y,z} vector')
    const v = bot.entity.position.clone(); Object.assign(v, { x: p.x, y: p.y, z: p.z }); return v
  }
  const block = p => {
    const v = vector(p)
    if (![v.x, v.y, v.z].every(Number.isSafeInteger)) throw new Error('Block coordinates must be integers')
    const b = bot.blockAt(v); if (!b) throw new Error('Block is not loaded'); return b
  }
  const entity = id => {
    if (!Number.isSafeInteger(id) || !bot.entities[id]) throw new Error('Unknown entity_id; observe again')
    return bot.entities[id]
  }
  const item = slot => {
    if (!Number.isSafeInteger(slot) || !bot.inventory.slots[slot]) throw new Error('Unknown inventory slot')
    return bot.inventory.slots[slot]
  }
  const items = list => list.map(i => i ? { slot: i.slot, name: i.name, type: i.type, count: i.count, metadata: i.metadata } : null)
  const window = () => { if (!bot.currentWindow) throw new Error('No window open'); return bot.currentWindow }
  const windowInfo = w => ({ id: w.id, type: w.type, title: String(w.title),
    inventory_start: w.inventoryStart, inventory_end: w.inventoryEnd,
    container_items: items(w.slots.slice(0, w.inventoryStart)),
    player_inventory: items(w.slots.slice(w.inventoryStart, w.inventoryEnd)), slots: items(w.slots) })
  const blockInfo = b => b ? { name: b.name, type: b.type, position: b.position,
    metadata: b.metadata, properties: b.getProperties() } : null
  const entityInfo = e => e ? { id: e.id, name: e.name, username: e.username,
    type: e.type, position: e.position, velocity: e.velocity, yaw: e.yaw, pitch: e.pitch } : null
  const method = (parameters, run, readOnly = false, interrupt = false) => ({ parameters, run, readOnly, interrupt })
  return {
    blockAt: method('position:{x,y,z}', p => blockInfo(bot.blockAt(vector(p.position))), true),
    blockAtCursor: method('max_distance?:number', p => blockInfo(bot.blockAtCursor(p.max_distance)), true),
    entityAtCursor: method('max_distance?:number', p => entityInfo(bot.entityAtCursor(p.max_distance)), true),
    nearestEntity: method('no parameters; nearest client-known entity', () => entityInfo(bot.nearestEntity()), true),
    entities: method('no parameters; all client-known entities', () => Object.values(bot.entities).map(entityInfo), true),
    findBlocks: method('matching:integer block type or integer array, point?:{x,y,z}, maxDistance?:number, count?:integer', p => {
      if (!(Number.isInteger(p.matching) || (Array.isArray(p.matching) && p.matching.every(Number.isInteger)))) throw new Error('matching must be block type IDs')
      const radius = p.maxDistance ?? 16, count = p.count ?? 10
      if (!Number.isInteger(radius) || radius < 1 || radius > 32 ||
          !Number.isInteger(count) || count < 1 || count > 20) throw new Error('Search radius must be 1..32 and count 1..20')
      return bot.findBlocks({ matching: p.matching, point: p.point ? vector(p.point) : undefined,
        maxDistance: radius, count })
    }, true),
    look: method('yaw:number, pitch:number (radians), force?:boolean', p => bot.look(p.yaw, p.pitch, p.force)),
    lookAt: method('point:{x,y,z}, force?:boolean', p => bot.lookAt(vector(p.point), p.force)),
    setControlState: method('control:forward|back|left|right|jump|sprint|sneak, state:boolean; persists until cleared', p => {
      if (!['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak'].includes(p.control) || typeof p.state !== 'boolean') throw new Error('Invalid control/state')
      bot.setControlState(p.control, p.state)
    }),
    getControlState: method('control:string', p => bot.getControlState(p.control), true),
    clearControlStates: method('no parameters', () => bot.clearControlStates(), false, true),
    setQuickBarSlot: method('slot:integer 0..8', p => bot.setQuickBarSlot(p.slot)),
    equip: method('slot:inventory slot, destination:hand|off-hand|head|torso|legs|feet', p => bot.equip(item(p.slot), p.destination)),
    unequip: method('destination:string', p => bot.unequip(p.destination)),
    toss: method('item_type:integer, metadata?:integer, count:integer', p => bot.toss(p.item_type, p.metadata ?? null, p.count)),
    tossStack: method('slot:inventory slot', p => bot.tossStack(item(p.slot))),
    consume: method('no parameters; consumes currently held item', () => bot.consume()),
    activateItem: method('off_hand?:boolean', p => bot.activateItem(p.off_hand)),
    deactivateItem: method('no parameters', () => bot.deactivateItem(), false, true),
    attack: method('entity_id:integer, swing?:boolean; submission only', p => bot.attack(entity(p.entity_id), p.swing)),
    swingArm: method('arm?:right|left, show_hand?:boolean', p => bot.swingArm(p.arm, p.show_hand)),
    activateEntity: method('entity_id:integer', p => bot.activateEntity(entity(p.entity_id))),
    activateEntityAt: method('entity_id:integer, point:{x,y,z}', p => bot.activateEntityAt(entity(p.entity_id), vector(p.point))),
    mount: method('entity_id:integer', p => bot.mount(entity(p.entity_id))),
    dismount: method('no parameters', () => bot.dismount()),
    moveVehicle: method('left:number, forward:number', p => bot.moveVehicle(p.left, p.forward)),
    dig: method('position:{x,y,z}, force_look?:boolean; native single-block dig, no navigation', p => { requireDiggingMode(bot); return bot.dig(block(p.position), p.force_look) }),
    stopDigging: method('no parameters; stops native digging', () => bot.stopDigging(), false, true),
    canDigBlock: method('position:{x,y,z}', p => bot.canDigBlock(block(p.position)), true),
    canSeeBlock: method('position:{x,y,z}', p => bot.canSeeBlock(block(p.position)), true),
    digTime: method('position:{x,y,z}', p => bot.digTime(block(p.position)), true),
    placeBlock: method('reference:{x,y,z}, face:{x,y,z}; uses held item, no auto-equip', p => bot.placeBlock(block(p.reference), vector(p.face))),
    activateBlock: method('position:{x,y,z}, direction?:{x,y,z}, cursor?:{x,y,z}', p => bot.activateBlock(block(p.position), p.direction ? vector(p.direction) : undefined, p.cursor ? vector(p.cursor) : undefined)),
    updateSign: method('position:{x,y,z}, text:string', p => bot.updateSign(block(p.position), p.text)),
    sleep: method('position:{x,y,z} of bed', p => bot.sleep(block(p.position))),
    wake: method('no parameters', () => bot.wake()),
    fish: method('no parameters; fishing rod should be held', () => bot.fish()),
    chat: method('message:string; native splitting/commands', p => bot.chat(p.message)),
    whisper: method('username:string, message:string', p => bot.whisper(p.username, p.message)),
    tabComplete: method('text:string, assume_command?:boolean', p => bot.tabComplete(p.text, p.assume_command)),
    inventory: method('no parameters; returns slot/type/count for reference conversion', () => items(bot.inventory.items()), true),
    currentWindow: method('no parameters', () => bot.currentWindow ? windowInfo(bot.currentWindow) : null, true),
    openContainer: method('position:{x,y,z}', async p => windowInfo(await bot.openContainer(block(p.position)))),
    openFurnace: method('position:{x,y,z}', async p => windowInfo(await bot.openFurnace(block(p.position)))),
    closeWindow: method('no parameters', () => bot.closeWindow(window()), false, true),
    clickWindow: method('slot:integer, mouse_button:integer, mode:integer', p => bot.clickWindow(p.slot, p.mouse_button, p.mode)),
    putAway: method('slot:integer', p => bot.putAway(p.slot)),
    moveSlotItem: method('source_slot:integer, destination_slot:integer', p => bot.moveSlotItem(p.source_slot, p.destination_slot)),
    deposit: method('item_type:integer, metadata?:integer, count:integer; open container required', p => window().deposit(p.item_type, p.metadata ?? null, p.count)),
    withdraw: method('item_type:integer, metadata?:integer, count:integer; open container required', p => window().withdraw(p.item_type, p.metadata ?? null, p.count)),
    furnacePutInput: method('item_type:integer, metadata?:integer, count:integer; open furnace required', p => window().putInput(p.item_type, p.metadata ?? null, p.count)),
    furnacePutFuel: method('item_type:integer, metadata?:integer, count:integer; open furnace required', p => window().putFuel(p.item_type, p.metadata ?? null, p.count)),
    furnaceTakeInput: method('no parameters; open furnace required', async () => items([await window().takeInput()])[0]),
    furnaceTakeFuel: method('no parameters; open furnace required', async () => items([await window().takeFuel()])[0]),
    furnaceTakeOutput: method('no parameters; open furnace required', async () => items([await window().takeOutput()])[0]),
    recipesAll: method('item_type:integer, metadata?:integer, crafting_table?:boolean', p => bot.recipesAll(p.item_type, p.metadata ?? null, p.crafting_table), true),
    recipesFor: method('item_type:integer, metadata?:integer, count:integer, table?:{x,y,z}', p => bot.recipesFor(p.item_type, p.metadata ?? null, p.count, p.table ? block(p.table) : null), true),
    craft: method('item_type:integer, recipe_index:integer (recipesAll with crafting_table=true), count:integer repetitions, table?:{x,y,z}; no automatic table selection', p => {
      const recipe = bot.recipesAll(p.item_type, p.metadata ?? null, true)[p.recipe_index]
      if (!recipe) throw new Error('Unknown recipe index')
      return bot.craft(recipe, p.count, p.table ? block(p.table) : null)
    })
  }
}

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
      requireDiggingMode(bot)
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

function createToolApi (state, dependencies) {
  const { messages, notifications = [], notificationEpoch, jobs, ready, observe, finish, inventoryAction,
    inventoryItem, inventorySnapshot, itemDefinition, nearbyTable, recipeKey,
    GoalNear, GoalFollow } = dependencies
  return function dispatch (method, path, args = {}) {
    // Named tools use a fixed method route and flat arguments; never take method from model input.
    if (method === 'POST' && path.startsWith('/native/')) {
      const { timeout_seconds, ...parameters } = args
      return dispatch('POST', '/native', { method: path.slice('/native/'.length), parameters, timeout_seconds })
    }
    const { bot, connected, pendingInventory, chatId } = state
    if (method === 'GET' && path === '/observe') return observe()
    // Internal adapter feed, available even while disconnected. Reads do not consume events.
    if (method === 'GET' && path === '/notifications') {
      const after = Number(args.after || 0)
      if (!Number.isSafeInteger(after) || after < 0) throw new Error('Invalid notification cursor')
      const latest = notifications.at(-1)?.id || 0
      const reset = (args.epoch !== undefined && args.epoch !== notificationEpoch) || after > latest
      const cursor = reset ? 0 : after
      return { epoch: notificationEpoch, next_cursor: latest, cursor_reset: reset,
        truncated: notifications.length > 0 && cursor < notifications[0].id - 1,
        notifications: notifications.filter(event => event.id > cursor) }
    }
    // 返回游标之后的聊天及 next_cursor；truncated 表示旧消息已被缓存淘汰。
    if (method === 'GET' && path === '/chat') {
      const after = Number(args.after || 0)
      if (!Number.isSafeInteger(after) || after < 0) throw new Error('Invalid chat cursor')
      const cursorReset = after > chatId
      const effectiveAfter = cursorReset ? 0 : after
      return { messages: messages.filter(m => m.id > effectiveAfter), next_cursor: chatId,
        cursor_reset: cursorReset,
        truncated: messages.length > 0 && effectiveAfter < messages[0].id - 1 }
    }
    // 按 ID 查询最近 100 个移动任务；未知或已淘汰的 ID 返回错误。
    if (method === 'GET' && path.startsWith('/actions/')) {
      // 创建任务记录和超时计时器；超时后将任务标为失败并停止寻路。
      const job = jobs.get(path.slice('/actions/'.length))
      if (!job) throw new Error('Unknown or expired action ID')
      return { ...job }
    }
    // 取消当前任务并清空寻路目标，不撤销已经发生的位移。
    if (method === 'POST' && path === '/stop') {
      if (pendingInventory) return { stopped: false, action_id: pendingInventory.id,
        reason: 'Inventory operation cannot be safely cancelled; wait for action_status pending=false' }
      const id = state.active?.job.id || null
      const digging = state.active?.job.kind === 'dig_blocks'
      finish('cancelled', 'Cancelled by agent; changes already made are not undone')
      if (digging) bot.stopDigging()
      if (connected) {
        bot.pathfinder.setGoal(null)
        bot.clearControlStates()
      }
      return { stopped: true, action_id: id }
    }
    ready()
    // Canonicalize item arguments consistently for lookup, inventory comparisons and placement.
    if (Object.hasOwn(args, 'item')) args = { ...args, item: normalizeItemName(args.item) }
    if (method === 'GET' && path === '/items/search') {
      return searchItems(bot.registry, args.query, Number(args.offset ?? 0), Number(args.limit ?? 20))
    }
    if (method === 'GET' && path === '/native-methods') {
      return Object.fromEntries(Object.entries(nativeMethods(bot)).map(([name, spec]) =>
        [name, { parameters: spec.parameters, read_only: spec.readOnly, can_interrupt: spec.interrupt }]))
    }
    if (method === 'POST' && path === '/native') {
      const methods = nativeMethods(bot)
      if (!Object.hasOwn(methods, args.method)) throw new Error('Unsupported native method; call native_methods')
      const spec = methods[args.method], parameters = args.parameters ?? {}
      if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('parameters must be an object')
      if (spec.readOnly || spec.interrupt) {
        const result = spec.run(parameters)
        if (result && typeof result.then === 'function') return result.then(value => ({ method: args.method, result: value ?? null }))
        return { method: args.method, result: result ?? null }
      }
      const timeout = args.timeout_seconds ?? 120
      if (!Number.isInteger(timeout) || timeout < 1 || timeout > 600) throw new Error('timeout_seconds must be 1..600')
      return inventoryAction('native', { method: args.method }, async (actor, check) => {
        const result = await nativeMethods(actor)[args.method].run(parameters)
        check()
        return { method: args.method, result: result ?? null, completion_basis: 'native_call_returned',
          guidance: 'Native return does not prove server acceptance, damage, or item delivery.' }
      }, timeout)
    }
    if (method === 'POST' && ['/attack', '/hunt'].includes(path)) {
      if (state.active || pendingInventory) throw new Error('An action is running; wait or stop it first')
      if (bot.currentWindow) throw new Error('Close the current window before attacking')
      if (!Number.isSafeInteger(args.entity_id) || args.entity_id < 0) throw new Error('Use an entity_id from observe')
      const target = bot.entities[args.entity_id]
      if (!target || target === bot.entity) throw new Error('Target is missing or is self; observe again')
      const seconds = args.timeout_seconds ?? 30
      const limit = path === '/hunt' ? (args.max_attacks ?? 20) : 1
      if (!Number.isInteger(seconds) || seconds < 1 || seconds > 120) throw new Error('timeout_seconds must be 1..120')
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('max_attacks must be 1..100')
      const actor = bot, origin = actor.entity.position.clone()
      if (target.position.distanceTo(origin) > 128) throw new Error('Target must be within 128 blocks')
      const job = { id: randomUUID(), kind: path === '/hunt' ? 'hunt_entity' : 'attack', status: 'running',
        cancellable: true, entity_id: target.id, phase: 'approaching', attacks_submitted: 0,
        target_hurt_events: 0, target_death_observed: false, kill_attribution: 'unknown',
        drops_collected_verified: false, max_attacks: limit }
      const alive = () => state.connected && state.bot === actor && state.active?.job === job
      const check = () => { if (!alive()) throw new Error('Action no longer active') }
      const ended = () => job.target_death_observed ? 'target_died'
        : actor.entities[target.id] !== target ? 'target_lost'
          : target.position.distanceTo(origin) > 128 || actor.entity.position.distanceTo(origin) > 128 ? 'pursuit_limit' : null
      const hurt = entity => { if (alive() && entity === target) job.target_hurt_events++ }
      const dead = entity => { if (alive() && entity === target) job.target_death_observed = true }
      const cleanup = () => {
        actor.removeListener('entityHurt', hurt)
        actor.removeListener('entityDead', dead)
        actor.pathfinder.setGoal(null)
        actor.clearControlStates()
      }
      jobs.set(job.id, job)
      if (jobs.size > 100) jobs.delete(jobs.keys().next().value)
      const timer = setTimeout(() => {
        if (!alive()) return
        job.end_reason = 'timeout'
        finish('failed', 'Pursuit timed out; inspect target and inventory before retrying')
      }, seconds * 1000)
      state.active = { job, timer, cleanup }
      actor.on('entityHurt', hurt)
      actor.on('entityDead', dead)
      ;(async () => {
        let reason
        while (alive()) {
          reason = await attackOnce(actor, target, check, { GoalFollow, ended, job })
          check()
          if (reason !== 'attack_submitted') break
          // Leave time for server feedback and prevent rapid repeated attack packets.
          job.phase = 'waiting'
          const until = Date.now() + 1000
          while (Date.now() < until && !ended()) {
            await new Promise(resolve => setTimeout(resolve, 100))
            check()
          }
          reason = ended()
          if (reason) break
          if (job.attacks_submitted >= limit) {
            reason = path === '/hunt' ? 'max_attacks' : 'attack_submitted'
            break
          }
        }
        check()
        job.end_reason = reason
        job.phase = 'finished'
        job.result = { end_reason: reason, attacks_submitted: job.attacks_submitted,
          target_hurt_events: job.target_hurt_events, target_death_observed: job.target_death_observed,
          kill_attribution: 'unknown', drops_collected_verified: false, inventory: inventorySnapshot(actor),
          guidance: 'Submitted attacks do not prove hits. Target hurt/death events do not identify the attacker. Target loss is not death; verify drops in inventory.' }
        finish(['target_lost', 'pursuit_limit'].includes(reason) ? 'failed' : 'completed')
      })().catch(error => {
        if (alive()) {
          job.end_reason = 'error'
          finish('failed', error.message)
        }
      })
      return { ...job }
    }
    if (pendingInventory && method === 'POST' && path !== '/chat') {
      throw new Error('Inventory operation still pending; wait for action_status before another action')
    }
    if (method === 'GET' && path === '/furnace') return furnaceInfo(bot)
    if (method === 'POST' && path === '/furnace/open') {
      if (bot.currentWindow) throw new Error('Close the current window first')
      if (!['x', 'y', 'z'].every(k => Number.isSafeInteger(args[k]))) throw new Error('Integer block coordinates required')
      const position = bot.entity.position.clone()
      Object.assign(position, { x: args.x, y: args.y, z: args.z })
      const block = bot.blockAt(position)
      if (!block || !['furnace', 'blast_furnace', 'smoker'].includes(block.name)) throw new Error('Expected a loaded furnace, blast_furnace or smoker')
      return inventoryAction('open_furnace', { position }, async (actor, check) => {
        await actor.openFurnace(block)
        check()
        return furnaceInfo(actor)
      })
    }
    if (method === 'POST' && ['/furnace/input', '/furnace/fuel', '/furnace/take'].includes(path)) {
      const w = furnaceWindow(bot)
      const taking = path === '/furnace/take'
      const methods = { input: 'takeInput', fuel: 'takeFuel', output: 'takeOutput' }
      let definition
      if (taking) {
        if (!Object.hasOwn(methods, args.slot)) throw new Error('slot must be input, fuel or output')
      } else {
        definition = itemDefinition(args.item)
        if (!Number.isSafeInteger(args.count) || args.count < 1 || args.count > 64) throw new Error('count must be 1..64')
      }
      const kind = taking ? 'take_furnace_item' : path.endsWith('/input') ? 'put_furnace_input' : 'put_furnace_fuel'
      return inventoryAction(kind, taking ? { slot: args.slot } : { item: args.item, count: args.count }, async (actor, check) => {
        if (actor.currentWindow !== w) throw new Error('Furnace window changed; open it again')
        if (taking) {
          if (!w[args.slot + 'Item']()) throw new Error('Selected furnace slot is empty; inspect_furnace before retrying')
          await w[methods[args.slot]]()
        } else {
          const available = w.slots.slice(w.inventoryStart, w.inventoryEnd)
            .filter(i => i && i.type === definition.id).reduce((sum, i) => sum + i.count, 0)
          if (available < args.count) throw new Error('Insufficient items in player inventory')
          await w[path.endsWith('/input') ? 'putInput' : 'putFuel'](definition.id, null, args.count)
        }
        check()
        if (actor.currentWindow !== w) throw new Error('Furnace window changed; inspect state before retrying')
        return { completion_basis: 'mineflayer_promise_resolved', furnace: furnaceInfo(actor),
          guidance: 'Transfer returned; inspect slots and inventory. This does not prove smelting completed.' }
      })
    }
    if (method === 'POST' && path === '/door/open') {
      if (!['x', 'y', 'z'].every(k => Number.isSafeInteger(args[k]))) throw new Error('Integer block coordinates required')
      if (bot.currentWindow) throw new Error('Close the current window first')
      const position = bot.entity.position.clone()
      Object.assign(position, { x: args.x, y: args.y, z: args.z })
      if (position.distanceTo(bot.entity.position) > 32) throw new Error('Door must be within 32 blocks')
      return inventoryAction('open_door', { position }, (actor, check) =>
        openDoor(actor, position, check, GoalNear, watchServerBlock), 25)
    }
    if (method === 'POST' && ['/use-on-block', '/interact-entity', '/sleep', '/wake'].includes(path)) {
      if (bot.currentWindow) throw new Error('Close the current window first')
      const position = { x: args.x, y: args.y, z: args.z }
      if (['/use-on-block', '/sleep'].includes(path) && !Object.values(position).every(Number.isSafeInteger)) {
        throw new Error('Integer block coordinates required')
      }
      const face = args.face ?? 'up'
      if (path === '/use-on-block' && !Object.hasOwn(FACES, face)) throw new Error('Invalid block face')
      if (path === '/interact-entity' && (!Number.isSafeInteger(args.entity_id) || !bot.entities[args.entity_id])) throw new Error('Unknown entity_id; observe again')
      if (args.item !== undefined) inventoryItem(args.item)
      const kind = { '/use-on-block': 'use_on_block', '/interact-entity': 'interact_entity', '/sleep': 'sleep', '/wake': 'wake' }[path]
      const details = path === '/interact-entity' ? { entity_id: args.entity_id, item: args.item }
        : path === '/wake' ? {} : { position, item: args.item, face }
      return inventoryAction(kind, details, async (actor, check) => {
        // Omitted item explicitly means empty main hand, never an accidental held tool.
        if (path === '/use-on-block' || path === '/interact-entity') {
          if (args.item !== undefined) await actor.equip(inventoryItem(args.item), 'hand')
          else await actor.unequip('hand')
          check()
        }
        const native = nativeMethods(actor)
        if (path === '/use-on-block') {
          const [x, y, z] = FACES[face]
          await native.activateBlock.run({ position, direction: { x, y, z },
            cursor: { x: 0.5 + x * 0.5, y: 0.5 + y * 0.5, z: 0.5 + z * 0.5 } })
        } else if (path === '/interact-entity') {
          await native.activateEntity.run({ entity_id: args.entity_id })
        } else if (path === '/sleep') await native.sleep.run({ position })
        else await native.wake.run({})
        check()
        return { completion_basis: 'native_call_returned', effect_verified: false,
          is_sleeping: actor.isSleeping, inventory: inventorySnapshot(actor),
          guidance: 'Inspect target and inventory before claiming a world effect or retrying. Sleeping does not mean the night has passed.' }
      })
    }
    if (method === 'GET' && path === '/container') {
      return nativeMethods(bot).currentWindow.run({})
    }
    if (method === 'POST' && path === '/container/open') {
      if (bot.currentWindow) throw new Error('Close the current container before opening another')
      if (!['x', 'y', 'z'].every(k => Number.isSafeInteger(args[k]))) throw new Error('Integer block coordinates required')
      return inventoryAction('open_container', { position: { x: args.x, y: args.y, z: args.z } }, async (actor, check) => {
        const result = await nativeMethods(actor).openContainer.run({ position: args })
        check()
        return result
      })
    }
    if (method === 'POST' && path === '/container/close') {
      return inventoryAction('close_container', {}, async (actor, check) => {
        if (actor.currentWindow) await nativeMethods(actor).closeWindow.run({})
        check()
        return { closed: !actor.currentWindow }
      })
    }
    if (method === 'POST' && ['/container/deposit', '/container/withdraw'].includes(path)) {
      const operation = path.endsWith('/deposit') ? 'deposit' : 'withdraw'
      const definition = itemDefinition(args.item)
      if (!Number.isSafeInteger(args.count) || args.count < 1 || args.count > 2304) throw new Error('count must be an integer from 1 to 2304')
      const window = bot.currentWindow
      if (!window || typeof window[operation] !== 'function') throw new Error('Open a storage container first')
      return inventoryAction(operation + '_item', { item: args.item, count: args.count }, async (actor, check) => {
        if (actor.currentWindow !== window) throw new Error('Container changed; open it again')
        const source = operation === 'deposit'
          ? window.slots.slice(window.inventoryStart, window.inventoryEnd)
          : window.slots.slice(0, window.inventoryStart)
        const available = source.filter(i => i && i.type === definition.id).reduce((sum, i) => sum + i.count, 0)
        if (available < args.count) throw new Error('Insufficient items in ' + (operation === 'deposit' ? 'inventory' : 'container'))
        await window[operation](definition.id, null, args.count)
        check()
        if (actor.currentWindow !== window) throw new Error('Container closed or changed; inspect state before retrying')
        return { item: args.item, requested_count: args.count,
          completion_basis: 'mineflayer_promise_resolved', container: nativeMethods(actor).currentWindow.run({}) }
      })
    }
    // Equip and consume use named inventory items, without changing the persona.
    if (method === 'POST' && path === '/equip') {
      const item = inventoryItem(args.item), destination = args.destination ?? 'hand'
      if (!['hand', 'off-hand', 'head', 'torso', 'legs', 'feet'].includes(destination)) throw new Error('Invalid equipment destination')
      return inventoryAction('equip', { item: args.item, destination }, async (actor, check) => {
        await actor.equip(item, destination)
        check()
        return { item: args.item, destination, completion_basis: 'mineflayer_promise_resolved' }
      })
    }
    if (method === 'POST' && path === '/consume') {
      const item = inventoryItem(args.item)
      return inventoryAction('consume', { item: args.item }, async (actor, check) => {
        await actor.equip(item, 'hand')
        check()
        await actor.consume()
        check()
        return { food: actor.food, health: actor.health, inventory: inventorySnapshot(actor) }
      })
    }
    if (method === 'POST' && path === '/drop') {
      if (bot.currentWindow) throw new Error('Close the open container before dropping inventory items')
      const item = inventoryItem(args.item)
      if (!Number.isSafeInteger(args.count) || args.count < 1 || args.count > 2304) throw new Error('count must be an integer from 1 to 2304')
      const countItems = actor => actor.inventory.items().filter(i => i.name === args.item).reduce((sum, i) => sum + i.count, 0)
      if (countItems(bot) < args.count) throw new Error('Insufficient items in inventory')
      return inventoryAction('drop', { item: args.item, count: args.count }, async (actor, check) => {
        const before = countItems(actor)
        if (before < args.count) throw new Error('Inventory changed; insufficient items')
        await actor.toss(item.type, null, args.count)
        check()
        const after = countItems(actor)
        return { item: args.item, requested_count: args.count, inventory_before: before,
          inventory_after: after, observed_decrease: before - after, recipient_pickup_verified: false,
          guidance: 'Drop operation finished. Inventory change may include concurrent pickups; no recipient delivery is verified.' }
      })
    }
    // Translate coordinates and face names, then delegate placement to Mineflayer.
    if (method === 'POST' && path === '/place') {
      const item = inventoryItem(args.item)
      const expected = bot.registry.blocksByName[args.item]
      if (!expected) throw new Error('Cannot verify placement for this item: no matching block registry name')
      if (!['x', 'y', 'z'].every(k => Number.isSafeInteger(args[k]))) throw new Error('Integer reference block coordinates required')
      const faces = { up: [0, 1, 0], down: [0, -1, 0], north: [0, 0, -1], south: [0, 0, 1], east: [1, 0, 0], west: [-1, 0, 0] }
      if (!Object.hasOwn(faces, args.face)) throw new Error('Invalid block face')
      const referencePosition = bot.entity.position.clone()
      Object.assign(referencePosition, { x: args.x, y: args.y, z: args.z })
      const face = bot.entity.position.clone()
      ;[face.x, face.y, face.z] = faces[args.face]
      const target = referencePosition.offset(face.x, face.y, face.z)
      const reference = bot.blockAt(referencePosition)
      if (!reference) throw new Error('Reference block is not loaded')
      return inventoryAction('place', { item: args.item, target }, async (actor, check) => {
        await actor.equip(item, 'hand')
        check()
        const update = watchServerBlock(actor, target)
        try {
          await actor.placeBlock(reference, face)
          check()
          // Wall-mounted forms have a different registry name from their item.
          const wallName = args.item === 'torch' ? 'wall_torch'
            : args.item.replace(/_torch$/, '_wall_torch').replace(/_sign$/, '_wall_sign')
          const matches = name => name === expected.name || name === wallName
          const observed = await update.wait(matches, () => state.connected && state.bot === actor && state.active?.job.kind === 'place')
          check()
          const after = actor.blockAt(target)
          if (!observed || !matches(observed.name) || !matches(after?.name)) {
            throw new Error(`Placement not confirmed: expected ${expected.name}, server update ${observed?.name ?? 'unavailable'}, client block ${after?.name ?? 'unavailable'}; inspect state before retrying`)
          }
          return { position: target, observed_block: after.name, server_placement_verified: true,
            completion_basis: 'server_block_update_matches_expected_block', inventory: inventorySnapshot(actor) }
        } finally {
          update.close()
        }
      })
    }
    // Recipe indexes refer to the full registry list, not the currently craftable subset.
    if (method === 'GET' && path === '/recipes') {
      const definition = itemDefinition(args.item), offset = Number(args.offset ?? 0)
      if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('Invalid recipe offset')
      const table = nearbyTable(), recipes = bot.recipesAll(definition.id, null, true)
      const available = new Set(bot.recipesFor(definition.id, null, 1, table).map(recipeKey))
      return { item: args.item, crafting_table: table?.position ?? null, total: recipes.length,
        next_offset: offset + 20 < recipes.length ? offset + 20 : null,
        recipes: recipes.slice(offset, offset + 20).map((recipe, i) => {
          const ingredients = recipe.delta.filter(d => d.count < 0).map(d => ({
            name: bot.registry.items[d.id]?.name ?? String(d.id), count: -d.count,
            available: bot.inventory.count(d.id, d.metadata) }))
          const materials = ingredients.every(item => item.available >= item.count)
          return { recipe_index: offset + i, output_count: recipe.result.count,
            requires_table: recipe.requiresTable, crafting_table_available: Boolean(table),
            materials_available: materials, craftable_once: available.has(recipeKey(recipe)),
            missing_requirements: [
              ...(!materials ? ['materials'] : []),
              ...(recipe.requiresTable && !table ? ['crafting_table'] : [])],
            ingredients }
        }) }
    }
    if (method === 'POST' && path === '/craft') {
      const definition = itemDefinition(args.item), repetitions = args.repetitions ?? 1, index = args.recipe_index
      if (!Number.isInteger(repetitions) || repetitions < 1 || repetitions > 16 || !Number.isSafeInteger(index) || index < 0) {
        throw new Error('Use a recipe_index from get_recipes and 1-16 repetitions')
      }
      const recipe = bot.recipesAll(definition.id, null, true)[index]
      if (!recipe) throw new Error('Unknown recipe index')
      const table = recipe.requiresTable ? nearbyTable() : null
      const wanted = recipe.result.count * repetitions
      return inventoryAction('craft', { item: args.item, recipe_index: index, repetitions, completed_repetitions: 0 }, async (actor, check, job) => {
        await actor.craft(recipe, repetitions, table)
        check()
        job.completed_repetitions = repetitions
        return { completed_repetitions: job.completed_repetitions, expected_output_count: wanted,
          inventory: inventorySnapshot(actor), guidance: 'Verify actual inventory; expected output is not an observed inventory delta.' }
      }, 120)
    }
    // Execute a bounded batch locally; the model need not supervise each block.
    if (method === 'POST' && path === '/dig-blocks') {
      if (state.active) throw new Error('An action is running; inspect or stop it first')
      const requested = args.blocks
      if (!Array.isArray(requested) || requested.length < 1 || requested.length > 16) {
        throw new Error('Provide 1-16 block coordinates')
      }
      const targets = requested.map(point => {
        if (!point || !['x', 'y', 'z'].every(k => Number.isSafeInteger(point[k]))) throw new Error('Integer block coordinates required')
        const position = bot.entity.position.clone()
        Object.assign(position, { x: point.x, y: point.y, z: point.z })
        const block = bot.blockAt(position)
        if (!block) throw new Error('Requested block is not loaded; inspect first')
        return { position, name: block.name, type: block.type }
      })
      if (new Set(targets.map(t => `${t.position.x},${t.position.y},${t.position.z}`)).size !== targets.length) throw new Error('Duplicate block coordinates')
      const seconds = args.timeout_seconds ?? 120
      if (!Number.isInteger(seconds) || seconds < 1 || seconds > 120) throw new Error('Invalid dig timeout')
      const first = targets[0]
      const job = { id: randomUUID(), kind: 'dig_blocks', status: 'running',
        target: first.position, block: first.name, completed_blocks: [], skipped_blocks: [], failed_blocks: [], unverified_blocks: [], remaining_blocks: targets.map(t => t.position),
        inventory_before: inventorySnapshot(bot) }
      jobs.set(job.id, job)
      if (jobs.size > 100) jobs.delete(jobs.keys().next().value)
      const digBot = bot
      const timer = setTimeout(() => {
        if (state.active?.job !== job) return
        finish('failed', 'Digging timed out; inspect progress before retrying')
        digBot.stopDigging()
      }, seconds * 1000)
      state.active = { job, target: first.position, timer }
      ;(async () => {
        await digBatch({ bot: digBot, targets, job,
          alive: () => state.connected && state.bot === digBot && state.active?.job === job })
        if (state.active?.job !== job) return
        job.result = { completion_basis: 'server_block_updates_for_completed_blocks', server_removal_verified: job.completed_blocks.length > 0,
          inventory: inventorySnapshot(digBot), drops_verified: false,
          guidance: 'Completed blocks received server air updates; skipped client-known air is unverified. Updates do not identify who removed a block or prove item pickup. Check inventory before claiming collected resources.' }
        job.phase = 'finished'
        finish(job.failed_blocks.length ? 'failed' : 'completed',
          job.failed_blocks.length ? 'Some targets could not be mined; inspect failed_blocks before choosing new targets' : undefined)
      })().catch(error => {
        if (state.active?.job === job) finish('failed', error.message)
      })
      return { ...job }
    }
    // 查询仅限已加载方块，结果不代表视线可见；限制范围和数量以避免过大响应。
    if (method === 'GET' && path === '/block') {
      const coords = ['x', 'y', 'z'].map(k => args[k] === undefined ? NaN : Number(args[k]))
      if (!coords.every(Number.isSafeInteger)) {
        const invalid = ['x', 'y', 'z'].filter((key, index) => !Number.isSafeInteger(coords[index]))
        throw new Error(`inspect_block: invalid coordinates ${invalid.join(', ')}; supply all of x, y, z as safe integers from an observed block position`)
      }
      const position = bot.entity.position.clone()
      ;[position.x, position.y, position.z] = coords
      if (position.distanceTo(bot.entity.position) > 32) throw new Error(`inspect_block: target is ${position.distanceTo(bot.entity.position).toFixed(1)} blocks away; maximum is 32. Move closer before inspecting`)
      const block = bot.blockAt(position)
      if (!block) return { loaded: false, position }
      return { loaded: true, name: block.name, position: block.position, properties: block.getProperties(),
        sign_text: block.signText ?? null, observation_scope: 'client-known block; not line-of-sight filtered' }
    }
    if (method === 'GET' && path === '/blocks') {
      const definition = bot.registry.blocksByName[args.name]
      const category = categories[args.name] || null
      if (!definition && !category) throw new Error(`find_blocks.name: unknown block name ${JSON.stringify(args.name)}. Use an exact block registry name such as oak_log or chest (without minecraft:), or a supported category: ${Object.keys(categories).join(', ')}. Generic log or wood is not supported`)
      const radius = Number(args.radius ?? 16), count = Number(args.count ?? 10)
      const invalid = []
      if (!Number.isInteger(radius) || radius < 1 || radius > 32) invalid.push(`radius=${JSON.stringify(args.radius)}; expected an integer from 1 to 32`)
      if (!Number.isInteger(count) || count < 1 || count > 20) invalid.push(`count=${JSON.stringify(args.count)}; expected an integer from 1 to 20`)
      if (invalid.length) throw new Error(`find_blocks: ${invalid.join('; ')}. To explore farther, move to another observed location and search again within these limits`)
      const positions = bot.findBlocks({ matching: category ? block => category.test(block.name) : definition.id, maxDistance: radius, count })
      return { blocks: positions.map(position => bot.blockAt(position)).filter(Boolean).map(block => blockInfo(bot, block)),
        observation_scope: 'loaded blocks only; not line-of-sight filtered; empty does not prove absence elsewhere' }
    }
    // Native chat handles message splitting and server command semantics.
    if (method === 'POST' && path === '/chat') {
      if (typeof args.message !== 'string') throw new Error('message must be a string')
      bot.chat(args.message)
      return { submitted: true, delivery_verified: false }
    }
    // 一次只运行一个移动任务：校验有限坐标、128 格距离限制及 1～120 秒超时。
    if (method === 'POST' && path === '/move') {
      if (state.active) throw new Error('Movement already running; inspect or stop it first')
      if (!['x', 'y', 'z'].every(k => typeof args[k] === 'number' && Number.isFinite(args[k]))) throw new Error('Finite coordinates required')
      const target = bot.entity.position.clone()
      Object.assign(target, { x: args.x, y: args.y, z: args.z })
      if (target.distanceTo(bot.entity.position) > 128) throw new Error('Target must be within 128 blocks')
      const seconds = args.timeout_seconds ?? 30
      if (!Number.isInteger(seconds) || seconds < 1 || seconds > 120) throw new Error('Invalid movement timeout')
      const radius = args.arrival_radius ?? 1
      if (![0, 1].includes(radius)) throw new Error('arrival_radius must be 0 or 1')
      const goal = new GoalNear(args.x, args.y, args.z, radius)
      // 创建任务记录和超时计时器；超时后将任务标为失败并停止寻路。
      const job = { id: randomUUID(), kind: 'move', status: 'running', target: { x: args.x, y: args.y, z: args.z } }
      jobs.set(job.id, job)
      if (jobs.size > 100) jobs.delete(jobs.keys().next().value)
      const timer = setTimeout(() => {
        job.result = { position: bot.entity.position.clone(), navigation_landmarks: landmarks(bot),
          guidance: 'Find an entrance or stairs and choose an intermediate waypoint. Open closed wooden doors with open_door. Do not repeatedly submit the same blocked target.' }
        finish('failed', 'Movement timed out; inspect current position before retrying')
        bot.pathfinder.setGoal(null)
      }, seconds * 1000)
      // 异步提交寻路目标并立即返回任务；是否到达需查询状态，不能把 running 当作完成。
      state.active = { job, target, timer }
      const actor = bot
      Promise.resolve().then(() => {
        if (state.active?.job !== job || state.bot !== actor) return
        return actor.pathfinder.goto(goal)
      }).then(() => {
        if (state.active?.job === job && state.bot === actor) {
          // goto can resolve on an empty path even when the target was not reached.
          const position = actor.entity.position.clone()
          const standingBlock = { x: Math.floor(position.x), y: Math.floor(position.y), z: Math.floor(position.z) }
          if (!goal.isEnd(standingBlock)) {
            actor.pathfinder.setGoal(null)
            throw new Error('Pathfinder stopped before reaching the target; inspect position and choose entrance/stair/landing waypoints')
          }
          job.result = { position, arrival_radius: radius, arrived: true,
            completion_basis: 'client_position_satisfies_goal' }
          finish('completed')
        }
      }).catch(error => {
        if (state.active?.job === job) {
          job.result = { position: actor.entity.position.clone(), navigation_landmarks: landmarks(actor),
            arrived: false, arrival_radius: radius,
            guidance: 'Inspect entrances and stairs. For an upstairs target, find the connected staircase and use arrival_radius=0 for observed walkable entrance, turn and landing waypoints. Coordinates refer to feet, not the supporting block. Verify height before targeting the bed; never repeat the same failed target.' }
          finish('failed', error.message)
        }
      })
      return { ...job }
    }
    throw new Error('Unknown operation')
  }
}

// 提供仅监听容器回环地址的 HTTP 服务：GET 读取查询参数，其他请求解析 JSON 正文。
function serve (bridge, port = 8765) {
  const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json')
    try {
      const url = new URL(req.url, 'http://localhost')
      // 限制正文字符串长度为 4096；当前逐块解码，尚未处理 UTF-8 字符跨块的情况。
      let body = ''
      for await (const chunk of req) {
        body += chunk.toString()
        if (body.length > 4096) throw new Error('Request too large')
      }
      const args = req.method === 'GET' ? Object.fromEntries(url.searchParams) : JSON.parse(body || '{}')
      res.end(JSON.stringify(await bridge.dispatch(req.method, url.pathname, args)))
    } catch (error) {
      // 当前将正文解析和业务错误统一映射为 HTTP 400。
      res.statusCode = 400
      res.end(JSON.stringify({ error: error.message,
        ...(Array.isArray(error.candidates) ? { candidates: error.candidates } : {}) }))
    }
  })
  server.listen(port, '127.0.0.1')
  return server
}


module.exports = { createToolApi, serve, nativeMethods, attackOnce, digBatch, watchServerBlock }
