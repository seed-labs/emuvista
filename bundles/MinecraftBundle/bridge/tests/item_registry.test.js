'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { searchItems, itemDefinition } = require('../item_registry')
const { createToolApi } = require('../tool_api')
const names = ['wooden_axe', 'iron_axe', 'oak_planks', 'stick', 'oak_log', 'oak_boat']
const items = names.map((name, id) => ({ id, name, displayName: name.replaceAll('_', ' ') }))
const registry = { itemsByName: Object.fromEntries(items.map(item => [item.name, item])), items }

test('registry search discovers names, supports spelling errors and pagination', () => {
  assert.deepEqual(searchItems(registry, 'axe').items.map(i => i.name), ['iron_axe', 'wooden_axe'])
  assert.equal(searchItems(registry, 'woodn_axe').items[0].name, 'wooden_axe')
  const first = searchItems(registry, 'axe', 0, 1)
  assert.equal(first.next_offset, 1)
  assert.equal(searchItems(registry, 'axe', first.next_offset, 1).items[0].name, 'wooden_axe')
  assert.equal(searchItems(registry, 'unrelatedzzzz').total, 0)
  assert.throws(() => searchItems(registry, ' ', 0, 20))
  assert.throws(() => searchItems(registry, 'axe', -1, 20))
})

test('exact lookup accepts vanilla namespaces but never auto-selects a candidate', () => {
  assert.equal(itemDefinition(registry, 'minecraft:wooden_axe'), registry.itemsByName.wooden_axe)
  assert.throws(() => itemDefinition(registry, 'oak_axe'), error => {
    assert.ok(error.candidates.some(i => i.name === 'wooden_axe'))
    assert.ok(error.candidates.every(i => registry.itemsByName[i.name]))
    return true
  })
  assert.throws(() => itemDefinition(registry, 'other:wooden_axe'))
})

function fixture () {
  let table = null, wood = 8
  const recipe = { result: { count: 1 }, requiresTable: true,
    delta: [{ id: 2, count: -3 }, { id: 3, count: -2 }, { id: 0, count: 1 }] }
  const bot = { registry, inventory: { count: id => id === 2 ? wood : 2 },
    recipesAll: () => [recipe], recipesFor: () => table && wood >= 3 ? [recipe] : [] }
  const dispatch = createToolApi({ bot, connected: true }, {
    ready: () => {}, itemDefinition: name => itemDefinition(registry, name),
    nearbyTable: () => table, recipeKey: JSON.stringify,
    inventoryAction: (kind, details) => ({ kind, ...details }) })
  return { dispatch, setTable: value => { table = value }, setWood: value => { wood = value } }
}

test('recipes distinguish table availability and material shortage', () => {
  const f = fixture()
  const query = () => f.dispatch('GET', '/recipes', { item: 'minecraft:wooden_axe' })
  let r = query().recipes[0]
  assert.equal(r.materials_available, true)
  assert.equal(r.crafting_table_available, false)
  assert.deepEqual(r.missing_requirements, ['crafting_table'])
  assert.equal(r.craftable_once, false)
  f.setTable({ position: { x: 1, y: 2, z: 3 } })
  r = query().recipes[0]
  assert.equal(r.craftable_once, true)
  assert.deepEqual(r.missing_requirements, [])
  f.setWood(1)
  r = query().recipes[0]
  assert.equal(r.crafting_table_available, true)
  assert.equal(r.materials_available, false)
  assert.deepEqual(r.missing_requirements, ['materials'])
})

test('HTTP dispatch exposes registry search and canonicalizes craft item names', () => {
  const { dispatch } = fixture()
  assert.equal(dispatch('GET', '/items/search', { query: 'axe', limit: '1' }).total, 2)
  assert.equal(dispatch('POST', '/craft', { item: 'minecraft:wooden_axe', recipe_index: 0 }).item, 'wooden_axe')
  assert.equal(dispatch('GET', '/recipes', { item: 'minecraft:wooden_axe' }).item, 'wooden_axe')
})
