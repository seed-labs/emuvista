<template>
  <page-header title="Bank accounts" balance back="/home" />
  <q-page-container>
    <q-page class="q-pa-md" style="max-width: 800px; margin: auto">
      <h1 class="text-h5">Bank accounts</h1>
      <p>Connect your bank once, then choose a bank account when confirming a transfer.</p>
      <p>Your bank password stays on the bank website. You can revoke access in your bank.</p>
      <q-banner v-if="error" class="bg-red-1 q-my-md" role="alert">{{ error }}</q-banner>
      <q-banner v-if="notice" class="bg-green-1 q-my-md">{{ notice }}</q-banner>
      <q-btn v-for="bank in banks" :key="bank.id" :label="'Connect ' + bank.name"
        color="primary" class="q-mr-sm" :loading="loading" @click="connect(bank.id)" />
      <q-btn label="Refresh" flat :loading="loading" @click="load" />
      <q-list bordered class="q-my-md">
        <q-item v-for="source in sources" :key="source.id">
          <q-item-section>
            <q-item-label>{{ source.label }} ····{{ source.maskedAccount }}</q-item-label>
            <q-item-label caption>{{ (source.balanceMinor / 100).toFixed(2) }} {{ source.currency }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn flat label="Disconnect bank" :disable="loading" @click="disconnect(source.connection)" />
          </q-item-section>
        </q-item>
        <q-item v-if="!sources.length"><q-item-section>No bank accounts connected.</q-item-section></q-item>
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

async function load() {
  loading.value = true
  error.value = ''
  try {
    banks.value = (await request<{ banks: typeof banks.value }>('/providers')).banks
    sources.value = (await request<{ sources: BankSource[] }>('/sources')).sources
    payments.value = (await request<{ payments: BankReceipt[] }>('/payments')).payments
  } catch (e) { error.value = e instanceof Error ? e.message : 'Unable to load bank accounts' }
  finally { loading.value = false }
}
async function connect(bank: string) {
  loading.value = true
  error.value = ''
  try {
    const result = await request<{ authorizationURL: string }>('/links', {
      bank, redirectURI: window.location.origin + '/bank-accounts'
    })
    window.location.assign(result.authorizationURL)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Unable to connect bank'
    loading.value = false
  }
}
async function disconnect(id: string) {
  loading.value = true
  try {
    await request('/links/remove', { id })
    await load()
  } catch (e) { error.value = e instanceof Error ? e.message : 'Unable to disconnect bank' }
  finally { loading.value = false }
}
onMounted(async () => {
  if (typeof route.query.code === 'string' && typeof route.query.state === 'string') {
    loading.value = true
    try {
      await request('/links/complete', { state: route.query.state, code: route.query.code })
      notice.value = 'Bank connected. You can now choose a bank account when sending a transfer.'
    } catch (e) { error.value = e instanceof Error ? e.message : 'Bank connection failed' }
    finally {
      await router.replace({ path: '/bank-accounts' })
      loading.value = false
    }
  } else if (route.query.error) {
    error.value = 'Bank authorization was not completed.'
    await router.replace({ path: '/bank-accounts' })
  }
  const authorizationError = error.value
  await load()
  if (authorizationError) error.value = authorizationError
})
</script>
