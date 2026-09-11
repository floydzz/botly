<script setup lang="ts">
defineProps<{ reason: string | null; loading: boolean }>()
const emit = defineEmits<{ takeover: [] }>()
</script>

<template>
  <div class="m-5 flex flex-col gap-4 rounded-lg border border-accent/25 bg-accent-dim p-4 sm:flex-row sm:items-center sm:justify-between">
    <div class="flex min-w-0 gap-3">
      <Icon name="ph:siren-bold" class="mt-0.5 size-4 shrink-0 text-accent" />
      <div>
        <p class="text-xs font-semibold text-accent">A person is needed</p>
        <p class="mt-1 text-xs leading-relaxed text-dim">{{ reason || 'The bot handed this conversation to the team.' }}</p>
      </div>
    </div>
    <button class="h-9 shrink-0 rounded-md bg-accent px-3.5 text-xs font-semibold text-ground transition-colors hover:bg-accent-lit disabled:opacity-60" :disabled="loading" @click="emit('takeover')">{{ loading ? 'Taking over…' : 'Take over' }}</button>
  </div>
</template>
