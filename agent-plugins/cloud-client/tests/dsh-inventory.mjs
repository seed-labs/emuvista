import assert from 'node:assert/strict'
import { Context } from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as CorePlugin from '../dist/client.js'

const expected = [
  'cloud_login', 'cloud_logout', 'cloud_account', 'cloud_list', 'cloud_stat',
  'cloud_mkdir', 'cloud_upload', 'cloud_download', 'cloud_move', 'cloud_delete',
  'cloud_share', 'cloud_list_shares', 'cloud_update_share', 'cloud_unshare',
  'cloud_copy', 'cloud_search', 'cloud_get_share', 'cloud_search_recipients',
  'cloud_list_trash', 'cloud_restore_trash', 'cloud_delete_permanently',
  'cloud_list_versions', 'cloud_restore_version',
]

const ctx = new Context()
await ctx.plugin(SystemPrompt, {})
await ctx.plugin(ToolRuntime)
await ctx.plugin(CorePlugin, {})

const actual = ctx.tools.schemas().map(schema => schema.name)
assert.deepEqual(actual, expected)
assert.equal(new Set(actual).size, 23)
process.stdout.write(`${JSON.stringify({ count: actual.length, tools: actual }, null, 2)}\n`)
process.stdout.write('DSH_CLOUD_INVENTORY_OK\n')
