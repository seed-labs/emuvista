<template>
  <q-layout view="hHh lpR fFf">
  <q-page-container>
    <q-page class="q-pa-lg" style="max-width: 700px; margin: auto">
      <h1 class="text-h4">Payment checkout</h1>
      <q-banner v-if="error" class="bg-red-1 q-my-md" role="alert">{{ error }}</q-banner>
      <template v-if="session">
        <h2 class="text-h6">Order {{ session.order }}</h2>
        <q-list bordered>
          <q-item v-for="item in session.allocations" :key="item.transferId">
            <q-item-section>{{ item.label }}</q-item-section>
            <q-item-section side>{{ (item.amountMinor / 100).toFixed(2) }} {{ session.currency }}</q-item-section>
          </q-item>
        </q-list>
        <p class="text-h6">Total: {{ (session.amountMinor / 100).toFixed(2) }} {{ session.currency }}</p>
        <p>Status: {{ session.status }}</p>
        <template v-if="session.status === 'paid'">
          <q-banner class="bg-green-1">Payment completed. Each seller has received their payment.</q-banner>
          <q-btn label="Return to shop" color="primary" class="q-mt-md" :href="session.returnURL" />
        </template>
        <q-form v-else-if="!token" @submit="login" class="q-gutter-md">
          <p>Sign in with your Payment account.</p>
          <q-input v-model="email" label="Payment email" type="email" autocomplete="username" />
          <q-input v-model="password" label="Payment password" type="password" autocomplete="current-password" />
          <q-btn type="submit" label="Sign in" color="primary" :loading="busy" />
        </q-form>
        <q-form v-else @submit="pay" class="q-gutter-md">
          <q-select v-model="payer" :options="accounts" option-value="id" option-label="name" emit-value map-options label="Wallet" :disable="busy" />
          <q-select v-model="source" :options="sources" emit-value map-options label="Pay with" :disable="busy" />
          <p>Card payments debit the selected bank card directly. Your payment balance stays unchanged.</p>
          <q-btn type="submit" label="Confirm payment" color="primary" :loading="busy" :disable="!payer || busy" />
          <q-btn label="Bank cards" flat to="/bank-accounts" target="_blank" />
        </q-form>
        <q-btn label="Return without another payment" flat class="q-mt-md" :href="session.returnURL" />
      </template>
    </q-page>
  </q-page-container>
  </q-layout>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { config } from '@/utils/config'
import type { BankSource } from '@/composables/funding'
interface Session { order: string; status: string; error?: string; currency: string; amountMinor: number; returnURL: string;
  allocations: { transferId: string; label: string; amountMinor: number }[] }
const route = useRoute()
const session = ref<Session>(), error = ref(''), busy = ref(false)
const email = ref(''), password = ref(''), token = ref(''), payer = ref(''), source = ref('balance')
const accounts = ref<{ id: string; name: string }[]>([])
const sources = ref([{ label: 'Payment balance', value: 'balance' }])
const base = config.ACCOUNTING_URL + '/' + encodeURIComponent(String(route.params.code))
const path = '/checkout/sessions/' + encodeURIComponent(String(route.params.id))
async function request(url: string, options: RequestInit = {}) {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json',
    ...(token.value ? { Authorization: 'Bearer ' + token.value } : {}), ...options.headers } })
  const body = await response.json()
  if (!response.ok) throw new Error(body.errors?.[0]?.detail || body.message || 'Payment request failed')
  return body
}
async function login() {
  busy.value = true; error.value = ''
  try {
    const result = await request(config.AUTH_URL + '/token', { method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'password', client_id: 'komunitin-app', username: email.value,
        password: password.value, scope: 'email accounting:read accounting:write' }) })
    token.value = result.access_token; password.value = ''
    const resultAccounts = await request(base + '/checkout/accounts')
    accounts.value = resultAccounts.accounts.map((account: { id: string; balanceMinor: number; name: string }) => ({
      id: account.id, name: `${account.name}: ${(account.balanceMinor / 100).toFixed(2)} ${session.value?.currency}` }))
    payer.value = accounts.value[0]?.id || ''
    const cards = await request(base + '/bank/sources')
    sources.value = [{ label: 'Payment balance', value: 'balance' }, ...cards.sources.filter((card: BankSource) => card.available).map((card: BankSource) => ({
      label: `${card.label} ····${card.maskedCard}`, value: card.id }))]
  } catch (e) { token.value = ''; error.value = e instanceof Error ? e.message : 'Sign in failed' }
  finally { busy.value = false }
}
async function pay() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    session.value = await request(base + path + '/pay', { method: 'POST', body: JSON.stringify({ payer: payer.value, source: source.value }) })
    if (session.value?.status !== 'paid') error.value = session.value?.error || 'Payment is pending; retry to check the same payment.'
  } catch (e) { error.value = e instanceof Error ? e.message : 'Payment failed' }
  finally { busy.value = false }
}
onMounted(async () => {
  try { session.value = await request(base + path) }
  catch (e) { error.value = e instanceof Error ? e.message : 'Checkout unavailable' }
})
</script>
