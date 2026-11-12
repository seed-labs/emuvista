import { useRawApiFetch } from '@/composables/useApiFetch'
import { config } from '@/utils/config'

export interface BankSource {
  id: string
  connection: string
  label: string
  currency: string
  balanceMinor: number
  maskedCard: string
  bank: string
  available: boolean
}
export interface BankReceipt {
  id: string
  status: string
  amountMinor: number
  source: string
  payer: string
  payee: string
  description: string
  payeeName: string
  currency: string
  ledgerHash?: string
  bankTransactionId?: number
  error?: string
}
export function useFunding(group: () => string) {
  const request = useRawApiFetch()
  return async <T>(path: string, body?: Record<string, unknown>): Promise<T> => {
    const response = await request(config.ACCOUNTING_URL + '/' + encodeURIComponent(group()) + '/bank' + path, {
      method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    })
    return response.json() as Promise<T>
  }
}
