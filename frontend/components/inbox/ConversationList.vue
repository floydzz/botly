<script setup lang="ts">
const props = defineProps<{ selectedId: number | null }>()
const store = useInboxStore()

const stateLabel = {
  bot: 'Bot',
  pending_human: 'Attention',
  human: 'Human',
  resolved: 'Resolved',
}

function displayName(name: string | null, reference: string) {
  return name?.trim() || `Customer ${reference.slice(-4)}`
}

function relative(value: string | null) {
  if (!value) return 'New'
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto', style: 'narrow' })
  if (Math.abs(seconds) < 60) return 'now'
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour')
  return formatter.format(Math.round(hours / 24), 'day')
}
</script>

<template>
  <section class="flex min-w-0 flex-col border-r border-line bg-surface/30">
    <header class="border-b border-line px-5 pb-4 pt-5">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="font-display text-xl font-semibold tracking-[-0.035em]">Inbox</h1>
          <p class="mt-0.5 text-xs text-mute">{{ store.counts.needs_attention }} waiting for a person</p>
        </div>
        <button
          class="grid size-9 place-items-center rounded-md border border-line text-dim transition-colors hover:border-lit hover:text-body"
          aria-label="Refresh inbox"
          :disabled="store.listLoading"
          @click="store.refresh()"
        >
          <Icon name="ph:arrow-clockwise-bold" class="size-4" :class="store.listLoading ? 'animate-spin' : ''" />
        </button>
      </div>

      <div class="mt-4 flex gap-2 overflow-x-auto pb-1 xl:hidden">
        <button class="shrink-0 rounded-full bg-raised px-3 py-1.5 text-[0.6875rem] text-body" @click="store.filters.state = []; store.filters.assignee = null; store.filters.unread = false; store.fetchList(true)">All {{ store.counts.all }}</button>
        <button class="shrink-0 rounded-full bg-accent-dim px-3 py-1.5 text-[0.6875rem] text-accent" @click="store.filters.state = ['pending_human']; store.filters.assignee = null; store.filters.unread = false; store.fetchList(true)">Attention {{ store.counts.needs_attention }}</button>
        <button class="shrink-0 rounded-full bg-raised px-3 py-1.5 text-[0.6875rem] text-dim" @click="store.filters.state = []; store.filters.assignee = 'me'; store.filters.unread = false; store.fetchList(true)">Mine {{ store.counts.mine }}</button>
        <button class="shrink-0 rounded-full bg-raised px-3 py-1.5 text-[0.6875rem] text-dim" @click="store.filters.state = []; store.filters.assignee = null; store.filters.unread = true; store.fetchList(true)">Unread {{ store.counts.unread }}</button>
      </div>
    </header>

    <div v-if="store.listLoading && !store.conversations.length" class="divide-y divide-line">
      <div v-for="index in 7" :key="index" class="animate-pulse px-5 py-5">
        <div class="h-3 w-28 bg-raised" /><div class="mt-3 h-3 w-4/5 bg-raised" /><div class="mt-3 h-2.5 w-20 bg-raised" />
      </div>
    </div>

    <div v-else-if="store.error && !store.conversations.length" class="grid flex-1 place-items-center px-6 text-center">
      <div><Icon name="ph:warning-circle-bold" class="mx-auto size-6 text-danger" /><p class="mt-3 text-sm">{{ store.error }}</p><button class="mt-3 text-xs font-medium text-accent" @click="store.refresh()">Try again</button></div>
    </div>

    <div v-else-if="!store.conversations.length" class="grid flex-1 place-items-center px-7 text-center">
      <div class="max-w-xs">
        <span class="mx-auto grid size-11 place-items-center rounded-lg border border-line bg-raised text-dim"><Icon name="ph:tray-bold" class="size-5" /></span>
        <h2 class="mt-4 font-display text-base font-semibold">Nothing in this queue</h2>
        <p class="mt-2 text-xs leading-relaxed text-mute">Try another filter, or wait for a connected channel to receive a message.</p>
      </div>
    </div>

    <ol v-else class="min-h-0 flex-1 overflow-y-auto" aria-label="Conversations">
      <li v-for="conversation in store.conversations" :key="conversation.id" class="border-b border-line">
        <NuxtLink
          :to="`/app/inbox/${conversation.id}`"
          class="group block px-5 py-4 transition-colors"
          :class="props.selectedId === conversation.id ? 'bg-raised' : 'hover:bg-surface'"
        >
          <div class="flex items-start gap-3">
            <span class="relative mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-[#1c2022] font-display text-xs font-semibold text-dim">
              {{ displayName(conversation.customer_name, conversation.customer_ref).charAt(0).toUpperCase() }}
              <span v-if="conversation.unread" class="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-accent ring-2 ring-surface" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="min-w-0 flex-1 truncate text-sm font-medium">{{ displayName(conversation.customer_name, conversation.customer_ref) }}</p>
                <time class="shrink-0 font-mono text-[0.575rem] text-mute">{{ relative(conversation.last_message_at) }}</time>
              </div>
              <p class="mt-1 truncate text-xs" :class="conversation.unread ? 'text-dim' : 'text-mute'">{{ conversation.last_message_preview || 'Attachment received' }}</p>
              <div class="mt-2 flex items-center gap-2">
                <span class="size-1.5 rounded-full bg-channel-telegram" />
                <span class="font-mono text-[0.55rem] uppercase tracking-[0.08em] text-mute">{{ conversation.provider }}</span>
                <span class="text-[0.6rem] text-mute">·</span>
                <span class="text-[0.625rem]" :class="conversation.handoff_state === 'pending_human' ? 'text-accent' : 'text-mute'">{{ stateLabel[conversation.handoff_state] }}</span>
                <Icon v-if="conversation.has_failed_delivery" name="ph:warning-circle-fill" class="ml-auto size-3.5 text-danger" aria-label="Last delivery failed" />
              </div>
            </div>
          </div>
        </NuxtLink>
      </li>
      <li v-if="store.nextCursor" class="p-4 text-center">
        <button class="text-xs font-medium text-accent disabled:text-mute" :disabled="store.listLoading" @click="store.fetchList(false)">{{ store.listLoading ? 'Loading…' : 'Load more' }}</button>
      </li>
    </ol>
  </section>
</template>
