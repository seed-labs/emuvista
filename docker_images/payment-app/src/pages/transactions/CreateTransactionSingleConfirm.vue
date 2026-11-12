<template>
  <q-form @submit="onSubmit">
    <div class="text-subtitle1 q-pb-lg">{{ $t('confirmTransaction') }}</div>
    <transaction-card :key="receipt?.status || 'confirmation'" :transfer="displayTransfer">
      <q-card-section v-if="bankEnabled">
        <q-select id="payment-source" v-model="source" :options="options" emit-value map-options label="Pay with" :disable="busy || !!receipt" />
        <q-btn flat label="Bank cards" to="/bank-accounts" class="q-mt-sm" />
        <p v-if="source !== 'balance'" class="text-caption q-mt-sm">Your bank account will be debited. Your payment balance will stay unchanged.</p>
        <p v-if="error" role="alert" class="text-negative">{{ error }}</p>
      </q-card-section>
      <q-card-section v-if="receipt" id="bank-payment-receipt">
        <div class="text-h6">{{ receipt.status === 'completed' ? 'Bank payment completed' : 'Bank payment: ' + receipt.status }}</div>
        <div>{{ (receipt.amountMinor / 100).toFixed(2) }}</div>
        <div v-if="receipt.bankTransactionId">Bank debit: {{ receipt.bankTransactionId }}</div>
        <div v-if="receipt.ledgerHash">Ledger credit: {{ receipt.ledgerHash }}</div>
        <p v-if="receipt.error">{{ receipt.error }}</p>
        
        <q-btn label="Payment home" flat to="/home" />
      </q-card-section>
      <q-separator inset />
      <q-card-actions v-if="!receipt" class="justify-end q-pa-md">
        <q-btn :label="$t('back')" color="primary" flat padding="xs lg" :disable="busy" @click="emit('back')" />
        <q-btn id="confirm-transaction" :label="$t('confirm')" type="submit" color="primary" padding="xs lg" unelevated :loading="busy" />
      </q-card-actions>
    </transaction-card>
  </q-form>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import type { DeepPartial } from 'quasar'
import { useQuasar } from 'quasar'
import TransactionCard from '../../components/TransactionCard.vue'
import { notifyTransactionState } from '../../plugins/NotifyTransactionState'
import type { Transfer, ExtendedTransfer } from '@/store/model'
import { config } from '@/utils/config'
import { useFunding, type BankSource, type BankReceipt } from '@/composables/funding'

const props = defineProps<{ code: string; transfer: DeepPartial<Transfer>; autoConfirm?: boolean }>()
const emit = defineEmits<{ (e: 'back'): void }>()
const store = useStore(), router = useRouter(), quasar = useQuasar(), { t } = useI18n()
const request = useFunding(() => props.code), source = ref('balance'), sources = ref<BankSource[]>([])
const receipt = ref<BankReceipt>(), busy = ref(false), error = ref('')
const operationId = ref(crypto.randomUUID())
const displayTransfer = computed(() => receipt.value ? {
  ...props.transfer,
  payer: (props.transfer as DeepPartial<ExtendedTransfer>).payer,
  payee: (props.transfer as DeepPartial<ExtendedTransfer>).payee,
  attributes: { ...props.transfer.attributes,
    state: receipt.value.status === 'completed' ? 'committed' : receipt.value.status === 'failed' ? 'failed' : 'pending' },
} : props.transfer)
const bankEnabled = computed(() => config.BANK_FUNDING_ENABLED && props.transfer.relationships?.payer?.data?.id === store.getters.myAccount?.id)
const options = computed(() => [{ label: 'Payment balance', value: 'balance' }, ...sources.value.filter(s => s.available).map(s => ({
  label: `Bank: ${s.label} ····${s.maskedCard} — ${(s.balanceMinor / 100).toFixed(2)} ${s.currency}`, value: s.id,
}))])
async function onSubmit() {
  if (busy.value || receipt.value) return
  busy.value = true; error.value = ''
  quasar.loading.show({ delay: 200 })
  try {
    if (source.value !== 'balance') {
      const payer = props.transfer.relationships?.payer?.data
      const payee = props.transfer.relationships?.payee?.data
      if (!payer?.id || !payee?.id || (payee as { meta?: { external?: boolean } }).meta?.external)
        throw new Error('Bank transfers currently require a recipient in the same community')
      const intent = {
        source: source.value, payer: payer.id, payee: payee.id,
        amountMinor: props.transfer.attributes?.amount,
        description: props.transfer.attributes?.meta?.description || 'Bank payment',
      }
      const key = 'pending-bank-payment:' + payer.id
      const previous = sessionStorage.getItem(key)
      if (previous) {
        const saved = JSON.parse(previous)
        if (saved.intent === JSON.stringify(intent)) operationId.value = saved.id
      }
      sessionStorage.setItem(key, JSON.stringify({ id: operationId.value, intent: JSON.stringify(intent) }))
      receipt.value = await request<BankReceipt>('/payments', { id: operationId.value, ...intent })
      if (['completed', 'failed'].includes(receipt.value.status)) sessionStorage.removeItem(key)
      if (receipt.value.status === 'completed') {
        try { sources.value = (await request<{ sources: BankSource[] }>('/sources')).sources } catch { /* Receipt remains authoritative. */ }
      }
    } else {
      await store.dispatch('transfers/create', { group: props.code, resource: {
        type: 'transfers', attributes: { ...props.transfer.attributes, state: 'committed' },
        relationships: { ...props.transfer.relationships },
      } })
      const created = store.getters['transfers/current']
      notifyTransactionState(created.attributes.state as string, t)
      await store.dispatch('accounts/load', { group: props.code, id: store.getters.myAccount.id })
      await router.push({ name: 'Transaction', params: { code: props.code, transferCode: created.id } })
    }
  } catch (e) { error.value = e instanceof Error ? e.message : 'Payment could not be confirmed' }
  finally { busy.value = false; quasar.loading.hide() }
}
onMounted(async () => {
  if (bankEnabled.value) {
    try { sources.value = (await request<{ sources: BankSource[] }>('/sources')).sources }
    catch { error.value = 'Bank accounts are unavailable. Payment balance is still available.' }
  }
  if (props.autoConfirm && !bankEnabled.value) await onSubmit()
})
</script>
