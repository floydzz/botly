<script setup lang="ts">
const store = useInboxStore()
const visibleProviders = computed(() => [...new Set([...store.providers, ...store.filters.provider])].sort())

const states = [
  { label: 'All conversations', icon: 'ph:chats-circle-bold', count: () => store.counts.all, state: null, assignee: null, unread: false },
  { label: 'Needs attention', icon: 'ph:siren-bold', count: () => store.counts.needs_attention, state: 'pending_human', assignee: null, unread: false },
  { label: 'Assigned to me', icon: 'ph:user-focus-bold', count: () => store.counts.mine, state: null, assignee: 'me', unread: false },
  { label: 'Unread', icon: 'ph:envelope-simple-bold', count: () => store.counts.unread, state: null, assignee: null, unread: true },
  { label: 'Resolved', icon: 'ph:check-circle-bold', count: () => store.counts.resolved, state: 'resolved', assignee: null, unread: false },
] as const

function active(item: typeof states[number]) {
  return store.filters.state[0] === item.state
    && store.filters.assignee === item.assignee
    && store.filters.unread === item.unread
}

async function select(item: typeof states[number]) {
  store.filters.state = item.state ? [item.state] : []
  store.filters.assignee = item.assignee
  store.filters.unread = item.unread
  await store.fetchList(true)
}

async function toggleProvider(provider: string) {
  store.filters.provider = store.filters.provider.includes(provider)
    ? store.filters.provider.filter(item => item !== provider)
    : [provider]
  await store.fetchList(true)
}
</script>

<template>
  <aside class="hidden min-w-0 border-r border-line bg-[#0b0d0f] xl:block">
    <div class="px-4 pb-3 pt-5">
      <p class="font-mono text-[0.625rem] uppercase tracking-[0.12em] text-mute">Queues</p>
    </div>
    <nav class="space-y-0.5 px-2" aria-label="Inbox filters">
      <button
        v-for="item in states"
        :key="item.label"
        class="flex min-h-10 w-full items-center gap-2.5 rounded-md px-3 text-left text-xs transition-colors"
        :class="active(item) ? 'bg-raised text-body' : 'text-dim hover:bg-surface hover:text-body'"
        @click="select(item)"
      >
        <Icon :name="item.icon" class="size-4 shrink-0" />
        <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
        <span class="font-mono text-[0.625rem] tabular-nums text-mute">{{ item.count() }}</span>
      </button>
    </nav>

    <div v-if="visibleProviders.length" class="mt-7 border-t border-line px-4 pb-3 pt-5">
      <p class="font-mono text-[0.625rem] uppercase tracking-[0.12em] text-mute">Channels</p>
      <div class="mt-3 space-y-1">
        <button
          v-for="provider in visibleProviders"
          :key="provider"
          class="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-xs capitalize transition-colors"
          :class="store.filters.provider.includes(provider) ? 'bg-raised text-body' : 'text-dim hover:text-body'"
          @click="toggleProvider(provider)"
        >
          <span class="size-2 rounded-full bg-channel-telegram" />
          {{ provider }}
          <Icon v-if="store.filters.provider.includes(provider)" name="ph:check-bold" class="ml-auto size-3" />
        </button>
      </div>
    </div>
  </aside>
</template>
