import { Router } from 'express'
import { z } from 'zod'
import type { BaseService } from '../controller'
import { Scope, userAuth } from '../server/auth'
import { asyncHandler } from '../server/handlers'
import { context } from '../utils/context'
import { badRequest } from '../utils/error'
import { BankFunding } from './funding'

const intent = z.object({ id: z.uuid(), source: z.string().regex(/^[a-f0-9]{32}$/), payer: z.uuid(), payee: z.uuid(),
  amountMinor: z.number().int().positive().max(100000000), description: z.string().trim().min(1).max(500) }).strict()

/** All bank operations use the existing wallet JWT and tenant boundary. */
export function getRoutes(service: BaseService) {
  const router = Router()
  router.use('/:code/bank', userAuth([Scope.AccountingWrite]))
  const route = (callback: (funding: BankFunding, body: unknown) => Promise<unknown>) =>
    asyncHandler(async (request, response) => {
      const currency = await service.getCurrencyController(request.params.code)
      const ctx = context(request)
      await currency.users.checkUser(ctx)
      const payload = request.auth?.payload
      const email = payload?.email_verified === true && typeof payload.email === 'string' ? payload.email.toLowerCase() : undefined
      const funding = new BankFunding(currency, ctx, email)
      response.json(await callback(funding, request.body))
    })
  router.get('/:code/bank/providers', route(async funding => ({ banks: funding.banks() })))
  router.get('/:code/bank/sources', route(funding => funding.sources()))
  router.get('/:code/bank/payments', route(funding => funding.history()))
  router.get('/:code/bank/payments/:id', asyncHandler(async (request, response) => {
    const currency = await service.getCurrencyController(request.params.code)
    await currency.users.checkUser(context(request))
    const funding = new BankFunding(currency, context(request))
    response.json(await funding.receipt(request.params.id))
  }))
  router.post('/:code/bank/links', route((funding, body) => {
    const result = z.object({ bank: z.string(), cardNumber: z.string().transform(value => value.replace(/[ -]/g, '')).pipe(z.string().regex(/^[0-9]{16,19}$/)), redirectURI: z.url() }).strict().safeParse(body)
    if (!result.success) throw badRequest('Bank, card number and callback address are required')
    return funding.begin(result.data.bank, result.data.cardNumber, result.data.redirectURI)
  }))
  router.post('/:code/bank/links/complete', route((funding, body) => {
    const result = z.object({ state: z.string().min(32).max(100), code: z.string().min(1).max(2000) }).strict().safeParse(body)
    if (!result.success) throw badRequest('Bank authorization response is invalid')
    return funding.finish(result.data.state, result.data.code)
  }))
  router.post('/:code/bank/links/remove', route((funding, body) => {
    const result = z.object({ id: z.string().regex(/^[a-f0-9]{32}$/) }).strict().safeParse(body)
    if (!result.success) throw badRequest('Card binding identifier is invalid')
    return funding.unlink(result.data.id)
  }))
  router.post('/:code/bank/payments', route((funding, body) => {
    const result = intent.safeParse(body)
    if (!result.success) throw badRequest('Bank transfer requires a valid amount, source and destination')
    return funding.pay(result.data)
  }))
  return router
}
