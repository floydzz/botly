<script setup lang="ts">
import type { CreditWallet, UsageRow } from '~/types/configuration'

definePageMeta({ layout: 'app' })
useHead({ title: 'Credits & usage · botly' })
const wallet = ref<CreditWallet | null>(null)
const usage = ref<UsageRow[]>([])
const loading = ref(true)
const error = ref('')
const more = ref(true)
const loadingMore = ref(false)
const number = (value: string | number | null | undefined) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 })
async function load() {
  loading.value = true; error.value = ''
  try {
    [wallet.value, usage.value] = await Promise.all([useApi().get<CreditWallet>('/billing/wallet'), useApi().get<UsageRow[]>('/billing/usage')])
    more.value = usage.value.length === 50
  } catch { error.value = 'Credits and usage could not be loaded.' }
  finally { loading.value = false }
}
async function nextPage() {
  loadingMore.value = true
  try {
    const rows = await useApi().get<UsageRow[]>(`/billing/usage?before_id=${usage.value.at(-1)?.id}`)
    usage.value.push(...rows); more.value = rows.length === 50
  } catch { error.value = 'More usage could not be loaded.' }
  finally { loadingMore.value = false }
}
onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-5xl px-5 py-10 md:px-8 md:py-14">
    <header class="flex flex-wrap items-end justify-between gap-4"><div><h1 class="font-display text-4xl tracking-tight">Credits & usage</h1><p class="mt-3 text-dim">One balance for every bot, model and channel.</p></div><UiButton variant="ghost" :loading="loading" @click="load">Refresh</UiButton></header>
    <p v-if="error" role="alert" class="mt-6 text-danger">{{ error }}</p>
    <p v-if="loading" class="mt-8 text-dim">Loading credits…</p>
    <template v-else-if="wallet">
      <div class="mt-8 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
        <div class="bg-surface p-6"><p class="text-sm text-dim">Available credits</p><p class="mt-4 text-3xl tabular-nums text-accent">{{ number(wallet.available) }}</p></div>
        <div class="bg-surface p-6"><p class="text-sm text-dim">Reserved for requests</p><p class="mt-4 text-3xl tabular-nums">{{ number(wallet.reserved) }}</p></div>
        <div class="bg-surface p-6"><p class="text-sm text-dim">Total balance</p><p class="mt-4 text-3xl tabular-nums">{{ number(wallet.balance) }}</p></div>
      </div>
      <p class="mt-5 text-sm text-dim">Credits reflect your model’s input and output rates. We reserve credits before a reply, then charge its actual usage. Uncertain requests stay reserved while reviewed. Contact your platform operator to add credits.</p>
      <h2 class="mt-10 text-lg font-medium">Model usage</h2>
      <div class="mt-4 overflow-x-auto rounded-lg border border-line">
        <table class="w-full whitespace-nowrap text-left text-sm"><thead class="border-b border-line bg-surface text-dim"><tr><th class="px-4 py-3">Model / time</th><th class="px-4 py-3">Input tokens</th><th class="px-4 py-3">Output tokens</th><th class="px-4 py-3">Credits charged</th><th class="px-4 py-3">Status</th></tr></thead>
          <tbody class="divide-y divide-line"><tr v-for="row in usage" :key="row.id"><td class="px-4 py-4">{{ row.model }}<span class="mt-1 block text-xs text-mute">{{ new Date(row.created_at).toLocaleString() }}</span></td><td class="px-4 py-4 tabular-nums">{{ number(row.input_tokens) }}</td><td class="px-4 py-4 tabular-nums">{{ number(row.output_tokens) }}</td><td class="px-4 py-4 tabular-nums">{{ number(row.charged_credits) }}</td><td class="px-4 py-4">{{ row.status }}<span v-if="['reserved', 'uncertain'].includes(row.status)" class="mt-1 block text-xs text-dim">{{ number(row.reserved_credits) }} held</span></td></tr><tr v-if="!usage.length"><td colspan="5" class="px-4 py-10 text-center text-dim">No model usage yet.</td></tr></tbody>
        </table>
      </div>
      <UiButton v-if="more && usage.length" class="mt-5" variant="ghost" :loading="loadingMore" @click="nextPage">Load more</UiButton>
    </template>
  </div>
</template>
