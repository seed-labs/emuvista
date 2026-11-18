import { Router } from 'express'
import { randomUUID, timingSafeEqual } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { Prisma } from '@prisma/client'
import { z } from 'zod'
import type { BaseService, CurrencyService } from '../controller'
import { Scope, userAuth } from '../server/auth'
import { asyncHandler } from '../server/handlers'
import { context, type Context } from '../utils/context'
import { badRequest, forbidden, notFound } from '../utils/error'
import { BankFunding } from '../bank/funding'

interface Merchant { id: string; secret: string; name: string; returnOrigins: string[]; notifyURL: string }
interface Allocation { payee: string; amountMinor: number; label: string; transferId: string }
interface Checkout {
  id: string; merchant: string; order: string; group: string; currency: string;
  allocations: Allocation[]; amountMinor: number; returnURL: string;
  status: string; created: string; owner?: string; payer?: string; source?: string;
  notified?: boolean; error?: string;
}
const queues = new Map<string, Promise<unknown>>()
async function serialize<T>(id: string, action: () => Promise<T>): Promise<T> {
  const previous = queues.get(id) ?? Promise.resolve()
  const operation = previous.catch(() => undefined).then(action)
  queues.set(id, operation)
  try { return await operation }
  finally { if (queues.get(id) === operation) queues.delete(id) }
}
function merchants(): Merchant[] {
  return process.env.PAYMENT_MERCHANT_CONFIG ? JSON.parse(readFileSync(process.env.PAYMENT_MERCHANT_CONFIG, 'utf8')) : []
}
function merchant(id: string, authorization?: string) {
  const value = merchants().find(item => item.id === id)
  const supplied = Buffer.from(authorization?.replace(/^Bearer /, '') ?? '')
  const expected = Buffer.from(value?.secret ?? '')
  if (!value || supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) throw forbidden('Merchant credentials are invalid')
  return value
}
const key = (id: string) => `checkout:session:${id}`
async function load(currency: CurrencyService, id: string): Promise<Checkout> {
  const row = await currency.db.value.findUnique({ where: { tenantId_key: { tenantId: currency.model.code, key: key(id) } } })
  if (!row) throw notFound('Checkout not found')
  return row.value as unknown as Checkout
}
async function save(currency: CurrencyService, session: Checkout) {
  await currency.db.value.update({ where: { tenantId_key: { tenantId: currency.model.code, key: key(session.id) } },
    data: { value: JSON.parse(JSON.stringify(session)) as Prisma.InputJsonValue } })
}
function publicSession(session: Checkout) {
  const { owner, payer, source, notified, ...result } = session
  return result
}
async function notify(currency: CurrencyService, session: Checkout) {
  if (session.status !== 'paid' || session.notified) return
  const receiver = merchants().find(item => item.id === session.merchant)
  if (!receiver) return
  try {
    // The receiver independently retrieves this receipt with its merchant secret.
    const result = await fetch(receiver.notifyURL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: session.id, group: session.group }), signal: AbortSignal.timeout(10000) })
    if (result.ok) { session.notified = true; await save(currency, session) }
  } catch { /* The checkout remains paid. Return-page verification can retry delivery. */ }
}
const input = z.object({ order: z.string().min(1).max(100), returnURL: z.url(),
  allocations: z.array(z.object({ payee: z.uuid(), amountMinor: z.number().int().positive().max(100000000),
    label: z.string().min(1).max(100) }).strict()).min(1).max(20) }).strict()

/** Orders and recipients are fixed by the merchant; only the payer chooses a funding source. */
export function getRoutes(service: BaseService) {
  const router = Router()
  router.post('/:code/checkout/merchants/:merchant/sessions', asyncHandler(async (req, res) => {
    const partner = merchant(req.params.merchant, req.headers.authorization)
    const parsed = input.safeParse(req.body)
    if (!parsed.success) throw badRequest('Checkout requires an order, return URL and positive recipient amounts')
    const data = parsed.data
    if (!partner.returnOrigins.includes(new URL(data.returnURL).origin)) throw badRequest('Return origin is not registered')
    const currency = await service.getCurrencyController(req.params.code)
    if (currency.model.scale !== 2) throw badRequest('Checkout currently supports two-decimal currencies')
    const sessionId = randomUUID()
    for (const item of data.allocations) {
      const account = await currency.accounts.getFullAccount(item.payee)
      if (account.status !== 'active') throw badRequest('Recipient wallet is not active')
    }
    const session: Checkout = { id: sessionId, merchant: partner.id, order: data.order, group: req.params.code,
      currency: currency.model.symbol, allocations: data.allocations.map(item => ({ ...item, transferId: randomUUID() })),
      amountMinor: data.allocations.reduce((sum, item) => sum + item.amountMinor, 0), returnURL: data.returnURL,
      status: 'unpaid', created: new Date().toISOString() }
    // One durable session per merchant order, including concurrent checkout submissions.
    await currency.db.value.create({ data: { key: key(session.id), value: JSON.parse(JSON.stringify(session)) as Prisma.InputJsonValue } })
    const index = `checkout:order:${partner.id}:${data.order}`
    await currency.db.value.upsert({ where: { tenantId_key: { tenantId: currency.model.code, key: index } },
      create: { key: index, value: { id: sessionId } }, update: {} })
    const winner = await currency.db.value.findUniqueOrThrow({ where: { tenantId_key: { tenantId: currency.model.code, key: index } } })
    const id = (winner.value as { id: string }).id
    if (id !== sessionId) {
      await currency.db.value.delete({ where: { tenantId_key: { tenantId: currency.model.code, key: key(session.id) } } })
      const existing = await load(currency, id)
      if (JSON.stringify(existing.allocations.map(item => [item.payee, item.amountMinor, item.label])) !== JSON.stringify(data.allocations.map(item => [item.payee, item.amountMinor, item.label])))
        throw badRequest('Order was already registered with different recipients or amounts')
      res.json(publicSession(existing)); return
    }
    res.json(publicSession(session))
  }))
  router.get('/:code/checkout/merchants/:merchant/sessions/:id', asyncHandler(async (req, res) => {
    const partner = merchant(req.params.merchant, req.headers.authorization)
    const session = await load(await service.getCurrencyController(req.params.code), req.params.id)
    if (session.merchant !== partner.id) throw forbidden('Checkout belongs to another merchant')
    res.json(publicSession(session))
  }))
  router.get('/:code/checkout/sessions/:id', asyncHandler(async (req, res) => {
    res.json(publicSession(await load(await service.getCurrencyController(req.params.code), req.params.id)))
  }))
  router.get('/:code/checkout/accounts', userAuth([Scope.AccountingWrite]), asyncHandler(async (req, res) => {
    const currency = await service.getCurrencyController(req.params.code)
    const ctx = context(req)
    await currency.users.checkUser(ctx)
    const accounts = await currency.db.account.findMany({ where: { users: { some: { userId: ctx.type === 'user' ? ctx.userId : '' } } } })
    res.json({ accounts: accounts.map(account => ({ id: account.id, balanceMinor: Number(account.balance), name: account.code })) })
  }))
  router.post('/:code/checkout/sessions/:id/pay', userAuth([Scope.AccountingWrite]), asyncHandler(async (req, res) => {
    const parsed = z.object({ payer: z.uuid(), source: z.string().regex(/^(balance|[a-f0-9]{32})$/) }).strict().safeParse(req.body)
    if (!parsed.success) throw badRequest('Choose a wallet and payment source')
    const currency = await service.getCurrencyController(req.params.code)
    const ctx = context(req)
    await currency.users.checkUser(ctx)
    const session = await serialize(req.params.id, async () => {
      const session = await load(currency, req.params.id)
      if (session.status === 'paid') return session
      await pay(currency, session, ctx, parsed.data)
      return session
    })
    await notify(currency, session)
    res.json(publicSession(session))
  }))
  return router
}
async function pay(currency: CurrencyService, session: Checkout, ctx: Context, data: { payer: string; source: string }) {
  const account = await currency.accounts.getFullAccount(data.payer)
  if (ctx.type !== 'user' || !account.users?.some(user => user.id === ctx.userId)) throw forbidden('Wallet belongs to another user')
  if (session.owner && (session.owner !== ctx.userId || session.payer !== data.payer || session.source !== data.source))
    throw badRequest('This checkout already has a payment attempt; retry with the original source')
  if (session.allocations.some(item => item.payee === data.payer)) throw badRequest('You cannot purchase from your own wallet')
  if (!session.owner && data.source === 'balance' && account.balance < session.amountMinor)
    throw badRequest('Payment balance is insufficient')
  session.owner = ctx.userId; session.payer = data.payer; session.source = data.source
  session.status = 'processing'; delete session.error
  await save(currency, session)
  try {
    for (const item of session.allocations) {
      const description = `Order ${session.order}: ${item.label}`
      if (data.source === 'balance') {
        const row = await currency.db.transfer.findUnique({ where: { tenantId_id: { tenantId: currency.model.code, id: item.transferId } } })
        const transfer = row ? await currency.transfers.getTransfer(ctx, item.transferId) :
          await currency.transfers.createTransfer(ctx, { id: item.transferId, amount: item.amountMinor, state: 'committed',
            payer: { type: 'accounts', id: data.payer }, payee: { type: 'accounts', id: item.payee }, meta: { description } })
        if (transfer.state !== 'committed' || transfer.amount !== item.amountMinor || transfer.payer.id !== data.payer || transfer.payee.id !== item.payee)
          throw badRequest('Transfer needs reconciliation; no replacement transfer has been created')
      } else {
        const receipt = await new BankFunding(currency, ctx).pay({ id: item.transferId, source: data.source,
          payer: data.payer, payee: item.payee, amountMinor: item.amountMinor, description })
        if (receipt.status !== 'completed') throw badRequest('Card payment is not yet completed; retry this checkout to check its receipt')
      }
    }
    session.status = 'paid'
  } catch (error) {
    session.status = 'pending'; session.error = error instanceof Error ? error.message : 'Payment requires review'
  }
  await save(currency, session)
}
