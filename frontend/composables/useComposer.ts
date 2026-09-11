import { computed, ref, type Ref } from 'vue'
import type { SendPolicy } from '../types/inbox'

export function chunkBoundaries(text: string, limit: number): number[] {
  if (limit <= 0) return []
  const boundaries: number[] = []
  let offset = 0
  let remaining = text.trim()
  while (remaining.length > limit) {
    const window = remaining.slice(0, limit)
    let cut = window.lastIndexOf('\n')
    if (cut <= 0) cut = window.lastIndexOf(' ')
    if (cut <= 0) cut = limit
    offset += cut
    boundaries.push(offset)
    const discarded = remaining.slice(cut).length - remaining.slice(cut).trimStart().length
    offset += discarded
    remaining = remaining.slice(cut).trimStart()
  }
  return boundaries
}

export function useComposer(policy: Ref<SendPolicy | null>) {
  const text = ref('')
  const disabled = computed(() => !policy.value?.can_send_freeform)
  const disabledReason = computed(() => policy.value?.reason || 'Take over the conversation to reply.')
  const remaining = computed(() => (policy.value?.max_text_len ?? 0) - text.value.length)
  const boundaries = computed(() => chunkBoundaries(text.value, policy.value?.max_text_len ?? 0))
  const overLimit = computed(() => remaining.value < 0)
  return { text, disabled, disabledReason, remaining, boundaries, overLimit }
}
