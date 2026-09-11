<script setup lang="ts">
import { ApiError } from '../../composables/useApi'

const store = useInboxStore()
const auth = useAuthStore()
const sending = ref(false)
const sendError = ref<string | null>(null)

const effectivePolicy = computed(() => {
  if (!store.detail) return null
  if (store.detail.handoff_state !== 'human') return { ...store.detail.send_policy, can_send_freeform: false, reason: 'Take over the conversation before replying.' }
  if (store.detail.assignee?.id !== auth.user?.id) return { ...store.detail.send_policy, can_send_freeform: false, reason: `${store.detail.assignee?.name || 'Another agent'} is handling this conversation.` }
  return store.detail.send_policy
})
const composer = useComposer(effectivePolicy)

async function submit() {
  const value = composer.text.value.trim()
  if (!value || composer.disabled.value || sending.value) return
  sending.value = true
  sendError.value = null
  try {
    await store.send(value)
    composer.text.value = ''
  } catch (error) {
    sendError.value = error instanceof ApiError ? error.detail : 'The reply could not be sent.'
  } finally {
    sending.value = false
  }
}

function keyboardSubmit(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') submit()
}
</script>

<template>
  <div class="border-t border-line bg-[#0b0d0f] p-4">
    <div v-if="composer.disabled.value" class="mb-3 flex items-start gap-2 text-xs text-mute">
      <Icon name="ph:lock-key-bold" class="mt-0.5 size-3.5 shrink-0" />
      <span>{{ composer.disabledReason.value }}</span>
    </div>
    <div v-if="sendError" class="mb-3 flex items-start gap-2 rounded-md border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger">
      <Icon name="ph:warning-circle-bold" class="mt-0.5 size-3.5 shrink-0" />{{ sendError }}
    </div>
    <div class="rounded-lg border border-line bg-surface transition-colors focus-within:border-lit">
      <textarea
        v-model="composer.text.value"
        aria-label="Reply"
        rows="3"
        class="block max-h-44 min-h-[5.5rem] w-full resize-y bg-transparent px-4 py-3 text-sm leading-relaxed text-body outline-none placeholder:text-mute disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="composer.disabled.value"
        :placeholder="composer.disabled.value ? 'Reply unavailable' : 'Write a reply…'"
        @keydown="keyboardSubmit"
      />
      <div class="flex items-center justify-between border-t border-line px-3 py-2">
        <div class="flex items-center gap-3 text-[0.625rem] text-mute">
          <span v-if="composer.boundaries.value.length" class="text-warn">Sends as {{ composer.boundaries.value.length + 1 }} messages</span>
          <span v-else><kbd class="font-mono">⌘ Enter</kbd> to send</span>
        </div>
        <div class="flex items-center gap-3">
          <span class="font-mono text-[0.625rem] tabular-nums" :class="composer.overLimit.value ? 'text-warn' : 'text-mute'">{{ composer.text.value.length }} / {{ effectivePolicy?.max_text_len || 0 }}</span>
          <button
            class="grid size-8 place-items-center rounded-md bg-accent text-ground transition-colors hover:bg-accent-lit disabled:cursor-not-allowed disabled:opacity-35"
            aria-label="Send reply"
            :disabled="composer.disabled.value || !composer.text.value.trim() || sending"
            @click="submit"
          >
            <Icon :name="sending ? 'ph:circle-notch-bold' : 'ph:arrow-up-bold'" class="size-4" :class="sending ? 'animate-spin' : ''" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
