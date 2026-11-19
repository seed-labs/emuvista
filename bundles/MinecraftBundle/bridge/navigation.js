'use strict'

const categories = {
  bed: /_bed$/,
  sign: /_sign$/,
  door: /_door$/,
  gate: /_fence_gate$/,
  stairs: /_stairs$/
}

function blockInfo (bot, block) {
  return { name: block.name, position: block.position,
    distance: block.position.distanceTo(bot.entity.position), properties: block.getProperties() }
}

// Separate quotas prevent nearby floors/walls from hiding entrances and stairs.
function landmarks (bot) {
  const result = {}
  for (const [kind, pattern] of Object.entries(categories)) {
    result[kind] = bot.findBlocks({
      matching: block => pattern.test(block.name) && block.getProperties().half !== 'upper',
      maxDistance: 32, count: 8
    }).map(p => bot.blockAt(p)).filter(Boolean).map(b => blockInfo(bot, b))
  }
  return result
}

async function openDoor (bot, position, check, GoalNear, watchServerBlock) {
  const read = () => {
    const block = bot.blockAt(position)
    if (!block || !(categories.door.test(block.name) || categories.gate.test(block.name))) {
      throw new Error('Target must be a loaded door or fence gate; search door/gate first')
    }
    if (block.name === 'iron_door') throw new Error('Iron doors require redstone; use another entrance or its control')
    return block
  }
  let block = read()
  if (block.getProperties().half === 'upper') position = position.offset(0, -1, 0)
  block = read()
  if (block.getProperties().open === true) {
    return { ...blockInfo(bot, block), already_open: true, server_open_verified: false }
  }
  // Explicit opening uses the configured engine to approach the target.
  let timer
  try {
    await Promise.race([
      bot.pathfinder.goto(new GoalNear(position.x, position.y, position.z, 2)),
      new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error('Door approach timed out')), 15000) })
    ])
  } finally {
    clearTimeout(timer)
    bot.pathfinder.setGoal(null)
  }
  check()
  block = read()
  if (block.getProperties().open === true) return { ...blockInfo(bot, block), already_open: true, server_open_verified: false }
  if (block.position.distanceTo(bot.entity.position) > 3 || !bot.canSeeBlock(block)) {
    throw new Error('Door is not within visible interaction reach; move to its other side/entrance first')
  }
  await bot.unequip('hand')
  check()
  block = read()
  if (block.getProperties().open === true) return { ...blockInfo(bot, block), already_open: true, server_open_verified: false }
  const update = watchServerBlock(bot, position)
  try {
    await bot.activateBlock(block)
    check()
    const received = await update.wait(() => {
      const current = bot.blockAt(position)
      return current?.name === block.name && current.getProperties().open === true
    }, () => { try { check(); return true } catch { return false } })
    check()
    const current = read()
    if (!received || received.state_id !== current.stateId || current.getProperties().open !== true) {
      throw new Error('Door opening not confirmed by server; inspect before retrying, do not blindly toggle')
    }
    return { ...blockInfo(bot, current), server_open_verified: true,
      guidance: 'Door is open; use move_to to a waypoint just inside, then navigate to your destination.' }
  } finally {
    update.close()
  }
}

module.exports = { categories, blockInfo, landmarks, openDoor }
