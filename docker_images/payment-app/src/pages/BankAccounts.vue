<template>
  <page-header title="Bank cards" balance back="/home" />
  <q-page-container>
    <q-page class="q-pa-md" style="max-width: 800px; margin: auto">
      <h1 class="text-h5">Bank cards</h1>
      <p>Add each card separately. Choose a card or payment balance when confirming a payment.</p>
      <p>Your bank verifies the card and its owner. Authorization applies only to that card.</p>
      <q-banner v-if="error" class="bg-red-1 q-my-md" role="alert">{{ error }}</q-banner>
      <q-banner v-if="notice" class="bg-green-1 q-my-md">{{ notice }}</q-banner>
      <q-form @submit="connect" class="q-gutter-md q-mb-md">
        <q-select v-model="selectedBank" :options="banks" option-value="id" option-label="name"
          emit-value map-options label="Bank" :disable="loading" />
        <q-input v-model="cardNumber" label="Card number" inputmode="numeric" autocomplete="off"
          :disable="loading" :rules="[value => /^[0-9 -]{16,25}$/.test(value) || 'Enter a card number']" />
        <q-btn label="Add bank card" type="submit" color="primary" :loading="loading" :disable="!selectedBank" />
      </q-form>
      <q-btn label="Refresh" flat :loading="loading" @click="load" />
      <q-list bordered class="q-my-md">
        <q-item v-for="source in sources" :key="source.id">
          <q-item-section>
            <q-item-label>{{ source.label }} ····{{ source.maskedCard }}</q-item-label>
            <q-item-label caption>{{ source.available ? (source.balanceMinor / 100).toFixed(2) + ' ' + source.currency : 'Card or bank unavailable' }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn flat label="Unlink card" :disable="loading" @click="disconnect(source.id)" />
          </q-item-section>
        </q-item>
        <q-item v-if="!sources.length"><q-item-section>No bank cards linked.</q-item-section></q-item>
      </q-list>
      <h2 class="text-h6">Bank transfers</h2>
      <q-card v-for="payment in payments" :key="payment.id" class="q-mb-md">
        <q-card-section>
          <div>{{ payment.description }} · {{ payment.status }}</div>
          <div class="text-caption">Transfer: {{ payment.id }}</div>
          <div v-if="payment.bankTransferId">Bank transfer: {{ payment.bankTransferId }}</div>
          <div v-if="payment.transferId">Wallet transfer: {{ payment.transferId }}</div>
          <p v-if="payment.error">{{ payment.error }}</p>
        </q-card-section>
      </q-card>
      <q-btn label="Wallet home" flat to="/home" />
    </q-page>
  </q-page-container>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useStore } from 'vuex'
import { useRouter, useRoute } from 'vue-router'
import PageHeader from '@/layouts/PageHeader.vue'
import { useFunding, type BankSource, type BankReceipt } from '@/composables/funding'

const store = useStore(), router = useRouter(), route = useRoute()
const group = computed(() => store.getters.myMember?.group?.attributes?.code || '')
const request = useFunding(() => group.value)
const banks = ref<{ id: string; name: string }[]>([])
const sources = ref<BankSource[]>([]), payments = ref<BankReceipt[]>([])
const loading = ref(false), error = ref(''), notice = ref('')
const selectedBank = ref(''), cardNumber = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    banks.value = (await request<{ banks: typeof banks.value }>('/providers')).banks
    if (!selectedBank.value) selectedBank.value = banks.value[0]?.id || ''
    sources.value = (await request<{ sources: BankSource[] }>('/sources')).sources
    payments.value = (await request<{ payments: BankReceipt[] }>('/payments')).payments
  } catch (e) { error.value = e instanceof Error ? e.message : 'Unable to load bank accounts' }
  finally { loading.value = false }
}
async function connect() {
  loading.value = true
  error.value = ''
  try {
    const result = await request<{ authorizationURL: string }>('/links', {
      bank: selectedBank.value, cardNumber: cardNumber.value.replace(/[ -]/g, ''), redirectURI: window.location.origin + '/bank-accounts'
    })
    window.location.assign(result.authorizationURL)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Unable to add card'
    loading.value = false
  }
}
async function disconnect(id: string) {
  loading.value = true
  try {
    await request('/links/remove', { id })
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : 'Unable to unlink card' }
  finally { loading.value = false }
}
onMounted(async () => {
  if (typeof route.query.code === 'string' && typeof route.query.state === 'string') {
    loading.value = true
    try {
      await request('/links/complete', { state: route.query.state, code: route.query.code })
      notice.value = 'Card linked. You can now choose this card when sending a payment.'
    } catch (e) { error.value = e instanceof Error ? e.message : 'Card binding failed' }
    finally {
      await router.replace({ path: '/bank-accounts' })
      loading.value = false
    }
  } else if (route.query.error) {
    error.value = 'Card authorization was not completed.'
    await router.replace({ path: '/bank-accounts' })
  }
  const authorizationError = error.value
  await load()
  if (authorizationError) error.value = authorizationError
})
</script>
