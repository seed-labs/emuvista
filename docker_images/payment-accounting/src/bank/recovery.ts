import { readFileSync } from 'node:fs'
import type { BaseService } from '../controller'
import { BankFunding } from './funding'

/** Finish previously submitted payments independently of agents and page reads. */
export function startBankRecovery(service: BaseService): () => void {
  const file = process.env.BANK_PROVIDER_CONFIG
  if (!file) return () => undefined
  const providers = JSON.parse(readFileSync(file, 'utf8')) as { group: string }[]
  const groups = [...new Set(providers.map(provider => provider.group))]
  let running = false
  const timer = setInterval(async () => {
    if (running) return
    running = true
    try {
      for (const code of groups) {
        try {
          const requests = await service.tenantDb(code).value.count({ where: { tenantId: code, key: { startsWith: 'bank:payment:' } } })
          if (requests) await BankFunding.recover(await service.getCurrencyController(code))
        }
        catch { /* A currency may still be initializing or temporarily unavailable. */ }
      }
    } finally { running = false }
  }, 10000)
  timer.unref()
  return () => clearInterval(timer)
}
