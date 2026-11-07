import { randomBytes, createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { Prisma } from '@prisma/client'
import type { CurrencyService } from '../controller'
import type { Context } from '../utils/context'
import { systemContext } from '../utils/context'
import { encrypt, decrypt } from '../utils/crypto'
import { badRequest, forbidden, notFound, transactionError } from '../utils/error'
import Big from 'big.js'

interface Provider {
  id: string
  name: string
  apiURL: string
  browserURL: string
  clientId: string
  clientSecret: string
  redirectURIs: string[]
  settlementWallet: string
  currency: string
  group: string
}
interface Tokens {
  access_token: string
  refresh_token?: string
  expires_in: number
}
interface Connection {
  id: string
  owner: string
  bank: string
  secret: string
  expires: number
  active: boolean
  cardId: string
  cardName: string
  maskedCard: string
  currency: string
}
interface Link {
  bank: string
  verifier: string
  redirectURI: string
  expires: number
  cardId: string
  cardName: string
  maskedCard: string
  currency: string
}
export interface BankIntent {
  id: string
  source: string
  payer: string
  payee: string
  amountMinor: number
  description: string
}
interface Receipt extends BankIntent {
  status: string
  created: string
  transferId?: string
  bankTransferId?: number
  error?: string
}
interface BankCard {
  cardId: string
  name: string
  maskedCard: string
  currency: string
  balanceMinor: number
}
interface CardConsent extends BankCard { consentId: string }

/** Native accounting feature; PostgreSQL stores authorization and operation state,
 * while Fineract and the existing Komunitin ledger retain their own balances. */
export class BankFunding {
  private providers: Provider[]

  constructor(private currency: CurrencyService, private ctx: Context, private walletEmail?: string) {
    if (ctx.type !== 'user' || !ctx.userId) throw forbidden('A wallet user is required')
    const file = process.env.BANK_PROVIDER_CONFIG
    this.providers = file ? (JSON.parse(readFileSync(file, 'utf8')) as Provider[])
      .filter(provider => provider.group === currency.model.code) : []
  }

  private key(name: string) {
    return `bank:${this.ctx.userId}:${name}`
  }

  private async get<T>(name: string): Promise<T | undefined> {
    const row = await this.currency.db.value.findUnique({ where: {
      tenantId_key: { tenantId: this.currency.model.code, key: this.key(name) }
    } })
    return row?.value as unknown as T | undefined
  }

  private async set(name: string, value: unknown) {
    const data = JSON.parse(JSON.stringify(value)) as Prisma.InputJsonValue
    await this.currency.db.value.upsert({ where: {
      tenantId_key: { tenantId: this.currency.model.code, key: this.key(name) }
    }, create: { key: this.key(name), value: data }, update: { value: data } })
  }

  private async list<T>(name: string): Promise<T[]> {
    const rows = await this.currency.db.value.findMany({ where: { tenantId: this.currency.model.code, key: { startsWith: this.key(name) } } })
    return rows.map(row => row.value as unknown as T)
  }

  banks() {
    return this.providers.map(provider => ({ id: provider.id, name: provider.name }))
  }

  private provider(id: string) {
    const provider = this.providers.find(provider => provider.id === id)
    if (!provider) throw notFound('Bank is not configured')
    return provider
  }

  private async bank<T>(provider: Provider, path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(provider.apiURL + path, { ...options, signal: AbortSignal.timeout(90000) })
    if (!response.ok) {
      const message = response.status === 400 ? 'Card or bank request was rejected' :
        response.status === 403 ? 'Bank authorization or card ownership verification failed' :
          `Bank request failed (${response.status})`
      const error = response.status === 400 ? badRequest(message) :
        response.status === 401 || response.status === 403 ? forbidden(message) : transactionError(message)
      throw Object.assign(error, { bankStatus: response.status })
    }
    return response.json() as Promise<T>
  }

  private token(provider: Provider, fields: Record<string, string>) {
    return this.bank<Tokens>(provider, '/oauth2/token', {
      method: 'POST', headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Authorization: 'Basic ' + Buffer.from(provider.clientId + ':' + provider.clientSecret).toString('base64')
      }, body: new URLSearchParams(fields)
    })
  }

  async begin(bank: string, cardNumber: string, redirectURI: string) {
    const provider = this.provider(bank)
    if (!this.walletEmail) throw forbidden('A verified wallet email is required to bind a card')
    if (!provider.redirectURIs.includes(redirectURI)) throw badRequest('Callback address is not registered')
    const credentials = await this.token(provider, { grant_type: 'client_credentials', scope: 'openbanking:consents' })
    const consent = await this.bank<CardConsent>(provider, '/openbanking/account-access-consents/cards', {
      method: 'POST', headers: { Authorization: 'Bearer ' + credentials.access_token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ cardNumber, walletOwnerEmail: this.walletEmail })
    })
    if (consent.currency !== provider.currency) throw badRequest('Card currency does not match this payment community')
    const existing = (await this.list<Connection>('connection:')).find(connection =>
      connection.active && connection.bank === bank && connection.cardId === consent.cardId)
    if (existing) throw badRequest('This card is already linked')
    const state = randomBytes(32).toString('base64url')
    const verifier = randomBytes(32).toString('base64url')
    const link: Link = { bank, verifier, redirectURI, expires: Date.now() + 600000,
      cardId: consent.cardId, cardName: consent.name, maskedCard: consent.maskedCard, currency: consent.currency }
    await this.set('link:' + state, { ...link, verifier: await encrypt(verifier, await this.currency.keys.encryptionKey()) })
    const url = new URL(provider.browserURL + '/api/v1/oauth2/authorize')
    url.search = new URLSearchParams({ response_type: 'code', client_id: provider.clientId,
      redirect_uri: redirectURI, scope: 'openbanking:cards.read openbanking:payments', state,
      code_challenge: createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256',
      consent_id: consent.consentId }).toString()
    return { authorizationURL: url.toString() }
  }

  async finish(state: string, code: string) {
    const link = await this.get<Link>('link:' + state)
    if (!link || link.expires < Date.now()) throw forbidden('Bank linking request expired or belongs to another user')
    const provider = this.provider(link.bank)
    const key = await this.currency.keys.encryptionKey()
    const tokens = await this.token(provider, { grant_type: 'authorization_code', code,
      redirect_uri: link.redirectURI, code_verifier: await decrypt(link.verifier, key) })
    const card = await this.bank<BankCard>(provider, '/openbanking/cards/current', {
      headers: { Authorization: 'Bearer ' + tokens.access_token }
    })
    if (card.cardId !== link.cardId || card.currency !== link.currency) throw forbidden('Bank returned another card')
    const id = createHash('sha256').update(link.bank + ':' + card.cardId).digest('hex').slice(0, 32)
    const connection: Connection = { id, owner: this.ctx.userId!, bank: link.bank,
      secret: await encrypt(JSON.stringify(tokens), key), expires: Date.now() + tokens.expires_in * 1000,
      active: true, cardId: card.cardId, cardName: card.name, maskedCard: card.maskedCard, currency: card.currency }
    const record = JSON.parse(JSON.stringify(connection)) as Prisma.InputJsonValue
    try {
      const existing = await this.get<Connection>('connection:' + id)
      if (existing) {
        const updated = await this.currency.db.value.updateMany({ where: {
          tenantId: this.currency.model.code, key: this.key('connection:' + id),
          value: { path: ['active'], equals: false }
        }, data: { value: record } })
        if (updated.count !== 1) throw badRequest('This card is already linked')
      } else {
        await this.currency.db.value.create({ data: { key: this.key('connection:' + id), value: record } })
      }
    } catch (error) {
      await this.bank(provider, '/openbanking/cards/current/revoke', {
        method: 'POST', headers: { Authorization: 'Bearer ' + tokens.access_token }
      })
      if ((error as { code?: string }).code === 'P2002') throw badRequest('This card is already linked')
      throw error
    }
    await this.currency.db.value.delete({ where: { tenantId_key: {
      tenantId: this.currency.model.code, key: this.key('link:' + state)
    } } })
    return { id }
  }

  private async access(connection: Connection) {
    const key = await this.currency.keys.encryptionKey()
    let tokens = JSON.parse(await decrypt(connection.secret, key)) as Tokens
    if (connection.expires < Date.now() + 30000) {
      if (!tokens.refresh_token) throw forbidden('Please reconnect this bank account')
      tokens = await this.token(this.provider(connection.bank), { grant_type: 'refresh_token', refresh_token: tokens.refresh_token })
      connection.secret = await encrypt(JSON.stringify(tokens), key)
      connection.expires = Date.now() + tokens.expires_in * 1000
      await this.set('connection:' + connection.id, connection)
    }
    return tokens.access_token
  }

  private async connection(id: string) {
    const connection = await this.get<Connection>('connection:' + id)
    if (!connection?.active || !connection.cardId || connection.owner !== this.ctx.userId)
      throw forbidden('Card is not linked to this wallet user')
    return connection
  }

  async unlink(id: string) {
    const connection = await this.connection(id)
    await this.bank(this.provider(connection.bank), '/openbanking/cards/current/revoke', {
      method: 'POST', headers: { Authorization: 'Bearer ' + await this.access(connection) }
    })
    connection.active = false
    connection.secret = ''
    await this.set('connection:' + id, connection)
    return { id }
  }

  async sources() {
    const connections = (await this.list<Connection>('connection:')).filter(connection => connection.active && connection.cardId)
    const sources = []
    for (const connection of connections) {
      const provider = this.provider(connection.bank)
      const item = { id: connection.id, connection: connection.id, bank: provider.id,
        label: provider.name + ' · ' + connection.cardName, maskedCard: connection.maskedCard,
        currency: connection.currency, balanceMinor: 0, available: false }
      try {
        const card = await this.bank<BankCard>(provider, '/openbanking/cards/current', {
          headers: { Authorization: 'Bearer ' + await this.access(connection) }
        })
        if (card.cardId !== connection.cardId || card.currency !== connection.currency) throw forbidden('Card changed')
        item.balanceMinor = card.balanceMinor
        item.available = true
      } catch { /* One unavailable bank must not hide other linked cards. */ }
      sources.push(item)
    }
    return { sources }
  }

  async history() {
    return { payments: (await this.list<Receipt>('payment:')).sort((a, b) => b.created.localeCompare(a.created)) }
  }

  async pay(intent: BankIntent): Promise<Receipt> {
    const existing = await this.get<Receipt>('payment:' + intent.id)
    if (existing) {
      if (Object.keys(intent).some(key => intent[key as keyof BankIntent] !== existing[key as keyof BankIntent])) {
        throw badRequest('Request identifier was already used for another transfer')
      }
      return existing
    }
    const connection = await this.connection(intent.source)
    const provider = this.provider(connection.bank)
    const payer = await this.currency.accounts.getFullAccount(intent.payer)
    if (!payer.users?.some(user => user.id === this.ctx.userId)) throw forbidden('Wallet account belongs to another user')
    const payee = await this.currency.accounts.getFullAccount(intent.payee)
    const reserve = await this.currency.accounts.getFullAccount(provider.settlementWallet)
    if (payer.status !== 'active' || payee.status !== 'active' || intent.payee === provider.settlementWallet
        || intent.payer === intent.payee || this.currency.model.symbol !== provider.currency) {
      throw badRequest('Bank transfers require active accounts in the configured currency')
    }
    if (reserve.balance < intent.amountMinor) throw transactionError('Wallet settlement balance is insufficient')
    const amount = Big(this.currency.toStringAmount(intent.amountMinor))
    if (!amount.eq(amount.round(2))) throw badRequest('Bank amount must have at most two decimal places')
    const access = await this.access(connection)
    const card = await this.bank<BankCard>(provider, '/openbanking/cards/current', {
      headers: { Authorization: 'Bearer ' + access }
    })
    if (card.cardId !== connection.cardId || card.currency !== provider.currency) throw forbidden('Card changed')
    const receipt: Receipt = { ...intent, status: 'pending', created: new Date().toISOString() }
    // Only the process that inserts the request may perform external writes.
    try {
      await this.currency.db.value.create({ data: {
        key: this.key('payment:' + intent.id), value: JSON.parse(JSON.stringify(receipt)) as Prisma.InputJsonValue
      } })
    } catch (error) {
      if ((error as { code?: string }).code !== 'P2002') throw error
      return this.pay(intent)
    }
    try {
      const bank = await this.bank<{ status: string; transferId?: number }>(provider, '/openbanking/payments', {
        method: 'POST', headers: { Authorization: 'Bearer ' + access, 'Content-Type': 'application/json', 'Idempotency-Key': intent.id },
        body: JSON.stringify({ cardId: connection.cardId, amount: amount.toFixed(2), currency: provider.currency })
      })
      receipt.bankTransferId = bank.transferId
      if (bank.status !== 'completed' || !bank.transferId) {
        receipt.status = bank.status === 'declined' ? 'failed' : 'needs_review'
        receipt.error = 'Bank did not confirm the debit'
      } else {
        receipt.status = 'bank_debited'
        await this.set('payment:' + intent.id, receipt)
        const transfer = await this.currency.transfers.createTransfer(systemContext(), {
          id: intent.id, amount: intent.amountMinor, state: 'committed',
          meta: { description: intent.description, bankFunding: intent.id },
          payer: { id: provider.settlementWallet, type: 'accounts' }, payee: { id: intent.payee, type: 'accounts' }
        })
        receipt.transferId = transfer.id
        receipt.status = transfer.state === 'committed' ? 'completed' : 'needs_review'
      }
    } catch (error) {
      const status = (error as { bankStatus?: number }).bankStatus
      receipt.status = status && status >= 400 && status < 500 ? 'failed' : 'needs_review'
      receipt.error = receipt.status === 'failed' ? 'Bank rejected this card payment' :
        'An uncertain transfer must be reconciled before another debit is attempted'
    }
    await this.set('payment:' + intent.id, receipt)
    return receipt
  }
}
