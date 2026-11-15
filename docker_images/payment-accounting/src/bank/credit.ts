import { Asset, BASE_FEE, Horizon, Memo, Networks, Operation, TransactionBuilder } from '@stellar/stellar-sdk'
import { createHash } from 'node:crypto'
import type { CurrencyService } from '../controller'
import { config } from '../config'

const queues = new Map<string, Promise<unknown>>()

/** Serialize issuer operations; a retry always broadcasts the same saved XDR. */
export async function serializePayment<T>(currency: string, action: () => Promise<T>): Promise<T> {
  const previous = queues.get(currency) ?? Promise.resolve()
  const operation = previous.catch(() => undefined).then(action)
  queues.set(currency, operation)
  try { return await operation }
  finally { if (queues.get(currency) === operation) queues.delete(currency) }
}

export interface ExternalCredit {
  id: string
  payee: string
  amountMinor: number
  ledgerHash?: string
  ledgerXdr?: string
}

/** Bank-confirmed external money enters the actual ledger, without a payer wallet. */
export async function creditBankPayment(currency: CurrencyService, credit: ExternalCredit, save: () => Promise<void>) {
  const server = new Horizon.Server(config.STELLAR_HORIZON_URL, { allowHttp: config.STELLAR_HORIZON_URL.startsWith('http:') })
  const network = { local: Networks.STANDALONE, testnet: Networks.TESTNET, public: Networks.PUBLIC }[config.STELLAR_NETWORK]
  const issuer = await currency.keys.issuerKey()
  const sponsor = await currency.keys.sponsorKey()
  const payee = await currency.accounts.getFullAccount(credit.payee)
  if (!credit.ledgerXdr) {
    const source = await server.loadAccount(issuer.publicKey())
    const asset = currency.ledger.asset()
    const inner = new TransactionBuilder(source, { fee: BASE_FEE, networkPassphrase: network })
      .addOperation(Operation.payment({ destination: payee.key, asset: new Asset(asset.code, asset.issuer),
        amount: currency.toStringAmount(credit.amountMinor) }))
      .addMemo(Memo.hash(createHash('sha256').update(credit.id).digest()))
      .setTimeout(300).build()
    inner.sign(issuer)
    const transaction = TransactionBuilder.buildFeeBumpTransaction(sponsor, BASE_FEE, inner, network)
    transaction.sign(sponsor)
    credit.ledgerXdr = transaction.toXDR()
    credit.ledgerHash = transaction.hash().toString('hex')
    // Persist before any network submission, including when recovering after a crash.
    await save()
  }
  let committed = false
  try { committed = (await server.transactions().transaction(credit.ledgerHash!).call()).successful }
  catch (error) {
    if ((error as { response?: { status: number } }).response?.status !== 404) throw error
  }
  if (!committed) {
    await server.submitTransaction(TransactionBuilder.fromXDR(credit.ledgerXdr, network))
  }
  const account = await currency.ledger.getAccount(payee.key)
  await account.update()
  await currency.accounts.updateAccountBalance(payee)
}
