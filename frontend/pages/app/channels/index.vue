<script setup lang="ts">
import type { BotConfig, ChannelConnection } from '~/types/configuration'
import { ApiError } from '~/composables/useApi'

definePageMeta({ layout: 'app' })
useHead({ title: 'Channels · botly' })
const channels = ref<ChannelConnection[]>([])
const bots = ref<BotConfig[]>([])
const botId = ref<number | null>(null)
const token = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const fieldClass = 'mt-2 w-full rounded-md border border-line bg-ground px-3 py-2.5 text-sm text-body focus:border-accent focus:outline-none'

async function load() {
  loading.value = true; error.value = ''
  try {
    [channels.value, bots.value] = await Promise.all([useApi().get<ChannelConnection[]>('/channels'), useApi().get<BotConfig[]>('/bots')])
    botId.value ??= bots.value[0]?.id ?? null
  } catch { error.value = 'Channels could not be loaded.' }
  finally { loading.value = false }
}

async function connect() {
  saving.value = true; error.value = ''; notice.value = ''
  try {
    await useApi().post('/channels/telegram', { bot_id: botId.value, bot_token: token.value })
    token.value = ''; notice.value = 'Telegram connected. Send your bot a message to start a conversation.'
    await load()
  } catch (cause) { error.value = cause instanceof ApiError ? cause.detail : 'Could not connect Telegram.' }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-5xl px-5 py-10 md:px-8 md:py-14">
    <h1 class="font-display text-4xl tracking-tight">Channels</h1>
    <p class="mt-3 text-dim">Connect Telegram to bring customer conversations into your inbox.</p>
    <p v-if="error" role="alert" class="mt-6 text-danger">{{ error }} <button class="underline" @click="load">Reload</button></p>
    <p v-if="notice" role="status" class="mt-6 text-ok">{{ notice }}</p>
    <p v-if="loading" class="mt-8 text-dim">Loading channels…</p>
    <template v-else>
      <form class="mt-8 rounded-lg border border-line bg-surface p-6" @submit.prevent="connect">
        <h2 class="text-lg font-medium">Connect a Telegram bot</h2>
        <p class="mt-2 text-sm text-dim">Create a bot with Telegram’s BotFather, then enter its token here. Reconnecting replaces its existing webhook.</p>
        <div class="mt-5 grid gap-5 md:grid-cols-2">
          <label class="text-sm text-dim">Botly bot<select v-model="botId" required :class="fieldClass"><option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }}</option></select></label>
          <label class="text-sm text-dim">BotFather token<input v-model="token" type="password" autocomplete="new-password" required minlength="10" maxlength="255" :class="fieldClass" /></label>
        </div>
        <p v-if="!bots.length" class="mt-4 text-sm text-dim"><NuxtLink to="/app/bots" class="text-accent underline">Create a Botly bot</NuxtLink> first.</p>
        <UiButton class="mt-5" type="submit" :loading="saving" :disabled="!botId">Connect Telegram</UiButton>
      </form>
      <div class="mt-8 divide-y divide-line border-y border-line">
        <div v-for="channel in channels" :key="channel.id" class="flex flex-wrap items-center justify-between gap-4 py-5">
          <div><p class="font-medium">{{ channel.username ? `@${channel.username}` : channel.external_ref }}</p><p class="mt-1 text-sm text-dim">{{ channel.provider }} · {{ bots.find(b => b.id === channel.bot_id)?.name || 'Bot' }}</p></div>
          <span class="rounded-md bg-raised px-3 py-1 text-sm" :class="channel.status === 'active' ? 'text-ok' : 'text-dim'">{{ channel.status }}</span>
        </div>
        <p v-if="!channels.length" class="py-8 text-sm text-dim">No channels connected yet.</p>
      </div>
    </template>
  </div>
</template>
