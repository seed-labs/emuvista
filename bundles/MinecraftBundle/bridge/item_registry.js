'use strict'

// Resolve names from the connected client's registry; never invent or auto-select items.
function normalizeItemName (name) {
  return typeof name === 'string' && name.startsWith('minecraft:') ? name.slice(10) : name
}

function distance (a, b) {
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    const current = [i]
    for (let j = 1; j <= b.length; j++) {
      current[j] = Math.min(current[j - 1] + 1, previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    }
    previous = current
  }
  return previous[b.length]
}

function searchItems (registry, query, offset = 0, limit = 20) {
  if (typeof query !== 'string' || !query.trim() || query.length > 100) throw new Error('query must contain 1-100 characters')
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 20) throw new Error('Invalid item search pagination')
  const text = normalizeItemName(query.trim().toLowerCase()).replace(/\s+/g, '_')
  const tokens = text.split('_').filter(Boolean)
  const matches = Object.values(registry.itemsByName).map(item => {
    const display = (item.displayName || '').toLowerCase().replace(/\s+/g, '_')
    const words = new Set((item.name + '_' + display).split('_'))
    const overlap = tokens.filter(token => words.has(token)).length
    const edit = distance(text, item.name)
    const score = item.name === text ? 1000 : item.name.includes(text) || display.includes(text) ? 500
      : edit <= Math.max(1, Math.floor(text.length / 5)) ? 300 - edit
        : overlap ? 100 + overlap * 10 + (words.has(tokens.at(-1)) ? 30 : 0) : 0
    return { item, score }
  }).filter(match => match.score > 0).sort((a, b) => b.score - a.score || a.item.name.localeCompare(b.item.name))
  return { query, total: matches.length, next_offset: offset + limit < matches.length ? offset + limit : null,
    items: matches.slice(offset, offset + limit).map(({ item }) => ({ name: item.name, display_name: item.displayName, id: item.id })),
    source: 'connected Minecraft item registry; matches do not imply a crafting recipe or available materials' }
}

function itemDefinition (registry, input) {
  const name = normalizeItemName(input)
  if (typeof name === 'string' && /^[a-z0-9_]{1,100}$/.test(name) && registry.itemsByName[name]) return registry.itemsByName[name]
  const candidates = typeof name === 'string' && name.trim() && name.length <= 100
    ? searchItems(registry, name, 0, 8).items : []
  const error = new Error('Unknown item name. Use minecraft.search_items to discover exact names.' +
    (candidates.length ? ' Possible matches: ' + candidates.map(item => item.name).join(', ') : ''))
  error.candidates = candidates
  throw error
}

module.exports = { normalizeItemName, searchItems, itemDefinition }
