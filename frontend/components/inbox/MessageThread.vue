<script setup lang="ts">
import { ApiError } from '../../composables/useApi'

const store = useInboxStore()
const auth = useAuthStore()
const actionError = ref<string | null>(null)
const scrollArea = ref<HTMLElement | null>(null)

const name = computed(() => store.detail?.customer_name?.trim() || `Customer ${store.detail?.customer_ref.slice(-4) || ''}`)
const heldByMe = computed(() => store.detail?.handoff_state === 'human' && store.detail.assignee?.id === auth.user?.id)

watch(() => store.messages.length, async () => {
  await nextTick()
  if (scrollArea.value) scrollArea.value.scrollTop = scrollArea.value.scrollHeight
})

function timestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

async function run(action: 'takeover' | 'release' | 'resolve') {
  actionError.value = null
  try {
    await store[action]()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.detail : 'The conversation could not be updated.'
  }
}

async function retry(text: string | null) {
  if (!text) return
  try {
    await store.send(text)
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.detail : 'The retry could not be sent.'
  }
}
</script>

<template>
  <section v-if="store.threadLoading" class="grid min-w-0 flex-1 place-items-center bg-ground">
    <div class="text-center"><Icon name="ph:circle-notch-bold" class="mx-auto size-5 animate-spin text-accent" /><p class="mt-3 text-xs text-mute">Opening conversation</p></div>
  </section>

  <section v-else-if="store.detail" class="flex min-h-0 min-w-0 flex-1 flex-col bg-ground">
    <header class="flex min-h-[5.25rem] items-center gap-3 border-b border-line px-4 sm:px-5">
      <NuxtLink to="/app/inbox" class="grid size-9 shrink-0 place-items-center rounded-md text-dim hover:bg-raised hover:text-body md:hidden" aria-label="Back to conversations"><Icon name="ph:arrow-left-bold" class="size-4" /></NuxtLink>
      <span class="grid size-10 shrink-0 place-items-center rounded-md bg-raised font-display text-sm font-semibold text-accent">{{ name.charAt(0).toUpperCase() }}</span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2"><h2 class="truncate font-display text-base font-semibold">{{ name }}</h2><span class="size-1.5 rounded-full bg-channel-telegram" /></div>
        <p class="mt-0.5 truncate text-[0.6875rem] text-mute">{{ store.detail.provider }} · {{ store.detail.bot.name }}<template v-if="store.detail.assignee"> · {{ store.detail.assignee.name }}</template></p>
      </div>
      <div class="flex shrink-0 items-center gap-1.5">
        <button v-if="heldByMe" class="hidden h-9 items-center gap-2 rounded-md border border-line px-3 text-xs text-dim hover:border-lit hover:text-body sm:flex" :disabled="store.actionLoading" @click="run('release')"><Icon name="ph:robot-bold" class="size-3.5" />Return to bot</button>
        <button v-if="store.detail.handoff_state !== 'resolved'" class="grid size-9 place-items-center rounded-md border border-line text-dim hover:border-lit hover:text-body" :disabled="store.actionLoading" aria-label="Resolve conversation" title="Resolve conversation" @click="run('resolve')"><Icon name="ph:check-bold" class="size-4" /></button>
        <button class="grid size-9 place-items-center rounded-md border border-line text-dim hover:border-lit hover:text-body" aria-label="More conversation options"><Icon name="ph:dots-three-bold" class="size-5" /></button>
      </div>
    </header>

    <InboxEscalationBanner
      v-if="store.detail.handoff_state === 'pending_human'"
      :reason="store.detail.escalation_reason"
      :loading="store.actionLoading"
      @takeover="run('takeover')"
    />

    <div v-if="actionError" class="mx-5 mt-4 flex items-start gap-2 rounded-md border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger"><Icon name="ph:warning-circle-bold" class="mt-0.5 size-3.5 shrink-0" />{{ actionError }}</div>

    <div ref="scrollArea" class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <button v-if="store.messagesCursor" class="mx-auto mb-6 block text-[0.6875rem] font-medium text-accent" @click="store.loadEarlier()">Load earlier messages</button>
      <div v-if="!store.messages.length" class="grid h-full place-items-center text-center"><div><Icon name="ph:chat-circle-dots-bold" class="mx-auto size-6 text-mute" /><p class="mt-3 text-sm text-dim">No messages in this thread yet.</p></div></div>
      <ol v-else class="mx-auto max-w-3xl space-y-5" aria-label="Message history">
        <li v-for="message in store.messages" :key="message.id" class="flex" :class="message.sender_type === 'customer' ? 'justify-start' : 'justify-end'">
          <div class="max-w-[82%] sm:max-w-[72%]">
            <div class="mb-1.5 flex items-center gap-2 px-1" :class="message.sender_type === 'customer' ? '' : 'justify-end'">
              <span class="font-mono text-[0.575rem] uppercase tracking-[0.08em] text-mute">{{ message.sender_type === 'customer' ? name : message.sender_type === 'bot' ? `${store.detail.bot.name} · Bot` : message.sender?.name || 'Agent' }}</span>
              <time class="text-[0.575rem] text-mute">{{ timestamp(message.created_at) }}</time>
            </div>
            <div
              class="rounded-lg border px-4 py-3 text-sm leading-relaxed"
              :class="message.sender_type === 'customer'
                ? 'border-line bg-surface text-body'
                : message.sender_type === 'bot'
                  ? 'border-[#274333] bg-[#102019] text-[#cce8d5]'
                  : 'border-accent/20 bg-accent-dim text-body'"
            >
              <p class="whitespace-pre-wrap break-words">{{ message.text || 'Attachment' }}</p>
              <div v-if="message.attachments.length" class="mt-3 border-t border-current/10 pt-3 text-xs opacity-70">{{ message.attachments.length }} attachment{{ message.attachments.length === 1 ? '' : 's' }}</div>
            </div>
            <div v-if="message.delivery_status === 'failed'" class="mt-2 flex items-start justify-end gap-2 text-right text-[0.6875rem] text-danger">
              <span>{{ message.error || 'Delivery failed' }}</span>
              <button class="font-semibold underline decoration-danger/40 underline-offset-2" @click="retry(message.text)">Retry</button>
            </div>
          </div>
        </li>
      </ol>
    </div>

    <InboxComposer />
  </section>

  <section v-else class="hidden min-w-0 flex-1 place-items-center bg-ground md:grid">
    <div class="max-w-sm px-8 text-center">
      <span class="mx-auto grid size-12 place-items-center rounded-lg border border-line bg-surface text-dim"><Icon name="ph:chats-circle-bold" class="size-5" /></span>
      <h2 class="mt-5 font-display text-lg font-semibold">Choose a conversation</h2>
      <p class="mt-2 text-sm leading-relaxed text-mute">Open a thread to see what the customer and bot have already said.</p>
    </div>
  </section>
</template>
