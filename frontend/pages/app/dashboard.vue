<script setup lang="ts">
import { ApiError } from '~/composables/useApi'

definePageMeta({ layout: 'app' })
useHead({ title: 'Dashboard · botly' })

type HandoffState = 'bot' | 'pending_human' | 'human' | 'resolved'

interface DashboardCounts {
  needs_attention: number
  unread: number
  bot_handling: number
  active_channels: number
  active_bots: number
}

interface RecentConversation {
  id: number
  customer_name: string
  customer_ref: string
  provider: string
  bot_name: string
  handoff_state: HandoffState
  last_message_at: string | null
  last_message_preview: string | null
  unread: boolean
}

interface DashboardSummary {
  counts: DashboardCounts
  recent_conversations: RecentConversation[]
}

const auth = useAuthStore()
const data = ref<DashboardSummary | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
})

const metrics = computed(() => [
  {
    label: 'Needs attention',
    value: data.value?.counts.needs_attention ?? 0,
    detail: 'Waiting for a person',
    icon: 'ph:warning-diamond-bold',
    tone: 'text-accent',
    to: '/app/inbox?state=pending_human',
  },
  {
    label: 'Unread',
    value: data.value?.counts.unread ?? 0,
    detail: 'New customer activity',
    icon: 'ph:envelope-simple-bold',
    tone: 'text-body',
    to: '/app/inbox?unread=true',
  },
  {
    label: 'Bot handling',
    value: data.value?.counts.bot_handling ?? 0,
    detail: 'Currently automated',
    icon: 'ph:robot-bold',
    tone: 'text-ok',
    to: '/app/inbox?state=bot',
  },
  {
    label: 'Active channels',
    value: data.value?.counts.active_channels ?? 0,
    detail: `${data.value?.counts.active_bots ?? 0} active ${data.value?.counts.active_bots === 1 ? 'bot' : 'bots'}`,
    icon: 'ph:broadcast-bold',
    tone: 'text-channel-telegram',
    to: '/app/channels',
  },
])

const stateLabels: Record<HandoffState, string> = {
  bot: 'Bot handling',
  pending_human: 'Needs attention',
  human: 'With an agent',
  resolved: 'Resolved',
}

const stateClasses: Record<HandoffState, string> = {
  bot: 'bg-ok/10 text-ok',
  pending_human: 'bg-accent-dim text-accent',
  human: 'bg-[#1b2630] text-[#8ec5e8]',
  resolved: 'bg-raised text-dim',
}

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await useApi().get<DashboardSummary>('/dashboard/summary')
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.status === 0
      ? 'The API could not be reached.'
      : 'Dashboard data could not be loaded.'
  } finally {
    loading.value = false
  }
}

function formatActivity(value: string | null) {
  if (!value) return 'No activity yet'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[1240px] px-5 py-10 md:px-8 md:py-14 xl:px-12">
    <header class="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
      <div>
        <p class="text-sm text-dim">{{ greeting }}, {{ auth.user?.name?.split(' ')[0] || 'there' }}</p>
        <h1 class="mt-2 font-display text-3xl font-medium tracking-[-0.045em] md:text-[2.6rem]">Here is what needs your attention.</h1>
      </div>
      <NuxtLink to="/app/inbox" class="inline-flex h-10 w-fit items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-ground transition-colors hover:bg-accent-lit active:scale-[0.98]">
        Open inbox
        <Icon name="ph:arrow-right-bold" class="size-4" />
      </NuxtLink>
    </header>

    <div v-if="error" class="mt-10 flex flex-col gap-4 rounded-lg border border-danger/30 bg-danger/5 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p class="text-sm font-medium text-danger">{{ error }}</p>
        <p class="mt-1 text-xs text-dim">The rest of the workspace is still available.</p>
      </div>
      <button class="h-9 rounded-md border border-danger/30 px-3 text-xs font-medium text-danger hover:bg-danger/10" @click="load">Try again</button>
    </div>

    <section class="mt-10 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 xl:grid-cols-4" aria-label="Dashboard metrics">
      <template v-if="loading">
        <div v-for="index in 4" :key="index" class="h-[10.5rem] animate-pulse bg-surface p-6">
          <div class="h-4 w-24 rounded-sm bg-raised" />
          <div class="mt-8 h-9 w-16 rounded-sm bg-raised" />
          <div class="mt-4 h-3 w-32 rounded-sm bg-raised" />
        </div>
      </template>
      <template v-else>
        <NuxtLink
          v-for="metric in metrics"
          :key="metric.label"
          :to="metric.to"
          class="group bg-surface p-6 transition-colors hover:bg-raised/70"
        >
          <div class="flex items-center justify-between">
            <p class="text-sm text-dim">{{ metric.label }}</p>
            <Icon :name="metric.icon" class="size-[1.125rem]" :class="metric.tone" />
          </div>
          <p class="mt-7 font-display text-4xl font-medium tabular-nums tracking-[-0.05em]">{{ metric.value }}</p>
          <div class="mt-4 flex items-center justify-between text-xs text-mute">
            <span>{{ metric.detail }}</span>
            <Icon name="ph:arrow-up-right-bold" class="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
        </NuxtLink>
      </template>
    </section>

    <div class="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1.65fr)_minmax(17rem,0.72fr)]">
      <section class="overflow-hidden rounded-lg border border-line bg-surface/65">
        <header class="flex items-center justify-between border-b border-line px-5 py-4 md:px-6">
          <div>
            <h2 class="font-display text-base font-semibold">Recent conversations</h2>
            <p class="mt-1 text-xs text-mute">Latest customer activity across your channels</p>
          </div>
          <NuxtLink to="/app/inbox" class="text-xs font-medium text-dim hover:text-body">View all</NuxtLink>
        </header>

        <div v-if="loading" class="divide-y divide-line">
          <div v-for="index in 4" :key="index" class="flex animate-pulse items-center gap-4 px-5 py-5 md:px-6">
            <div class="size-10 rounded-md bg-raised" />
            <div class="flex-1"><div class="h-3 w-28 bg-raised" /><div class="mt-3 h-3 max-w-sm bg-raised" /></div>
          </div>
        </div>

        <div v-else-if="!data?.recent_conversations.length" class="grid min-h-72 place-items-center px-6 py-12 text-center">
          <div class="max-w-sm">
            <span class="mx-auto grid size-11 place-items-center rounded-lg border border-line bg-raised text-dim"><Icon name="ph:chats-circle-bold" class="size-5" /></span>
            <h3 class="mt-5 font-display text-lg font-medium">No conversations yet</h3>
            <p class="mt-2 text-sm leading-relaxed text-dim">Messages will appear here after an active channel receives its first customer message.</p>
            <NuxtLink to="/app/channels" class="mt-5 inline-flex items-center gap-2 text-sm font-medium text-accent hover:text-accent-lit">Check channels <Icon name="ph:arrow-right-bold" class="size-4" /></NuxtLink>
          </div>
        </div>

        <div v-else class="divide-y divide-line">
          <NuxtLink
            v-for="conversation in data.recent_conversations"
            :key="conversation.id"
            :to="`/app/inbox/${conversation.id}`"
            class="group grid grid-cols-[auto_minmax(0,1fr)] gap-3 px-5 py-4 transition-colors hover:bg-raised/55 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center md:px-6"
          >
            <span class="relative grid size-10 place-items-center rounded-md bg-raised font-display text-sm font-semibold text-body">
              {{ conversation.customer_name.charAt(0).toUpperCase() }}
              <span v-if="conversation.unread" class="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-accent ring-2 ring-surface" />
            </span>
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <p class="truncate text-sm font-medium">{{ conversation.customer_name }}</p>
                <span class="font-mono text-[0.6rem] uppercase tracking-[0.08em] text-mute">{{ conversation.provider }}</span>
              </div>
              <p class="mt-1 truncate text-xs text-dim">{{ conversation.last_message_preview || 'Attachment received' }}</p>
            </div>
            <div class="col-start-2 flex items-center justify-between gap-4 md:col-auto md:block md:text-right">
              <span class="inline-flex rounded-full px-2 py-1 text-[0.625rem] font-medium" :class="stateClasses[conversation.handoff_state]">{{ stateLabels[conversation.handoff_state] }}</span>
              <p class="mt-1.5 text-[0.625rem] text-mute">{{ formatActivity(conversation.last_message_at) }}</p>
            </div>
          </NuxtLink>
        </div>
      </section>

      <aside class="space-y-8">
        <section class="rounded-lg border border-line bg-surface/65 p-6">
          <h2 class="font-display text-base font-semibold">Workspace setup</h2>
          <div class="mt-5 space-y-4">
            <NuxtLink to="/app/channels" class="group flex items-center gap-3">
              <span class="grid size-9 place-items-center rounded-md bg-raised text-channel-telegram"><Icon name="ph:broadcast-bold" class="size-4" /></span>
              <div class="min-w-0 flex-1"><p class="text-sm font-medium">Channels</p><p class="mt-0.5 text-xs text-mute">{{ data?.counts.active_channels || 0 }} active</p></div>
              <Icon name="ph:caret-right-bold" class="size-3.5 text-mute group-hover:text-body" />
            </NuxtLink>
            <NuxtLink to="/app/bots" class="group flex items-center gap-3">
              <span class="grid size-9 place-items-center rounded-md bg-raised text-ok"><Icon name="ph:robot-bold" class="size-4" /></span>
              <div class="min-w-0 flex-1"><p class="text-sm font-medium">Bots</p><p class="mt-0.5 text-xs text-mute">{{ data?.counts.active_bots || 0 }} configured</p></div>
              <Icon name="ph:caret-right-bold" class="size-3.5 text-mute group-hover:text-body" />
            </NuxtLink>
            <NuxtLink to="/app/knowledge" class="group flex items-center gap-3">
              <span class="grid size-9 place-items-center rounded-md bg-raised text-accent"><Icon name="ph:books-bold" class="size-4" /></span>
              <div class="min-w-0 flex-1"><p class="text-sm font-medium">Knowledge</p><p class="mt-0.5 text-xs text-mute">Not configured</p></div>
              <Icon name="ph:caret-right-bold" class="size-3.5 text-mute group-hover:text-body" />
            </NuxtLink>
          </div>
        </section>

        <section class="rounded-lg border border-line bg-[#101315] p-6">
          <div class="flex items-start gap-3">
            <Icon name="ph:info-bold" class="mt-0.5 size-4 shrink-0 text-accent" />
            <div>
              <h2 class="text-sm font-medium">Telegram is available now</h2>
              <p class="mt-2 text-xs leading-relaxed text-dim">WhatsApp and Shopee remain unavailable until their provider approvals clear.</p>
              <NuxtLink to="/app/channels" class="mt-4 inline-flex text-xs font-medium text-accent hover:text-accent-lit">View channel status</NuxtLink>
            </div>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
