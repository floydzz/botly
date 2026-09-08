<script setup lang="ts">
withDefaults(
  defineProps<{
    /** A semantic tone, or a raw CSS colour for a channel hue. */
    tone?: 'ok' | 'warn' | 'danger' | 'mute'
    color?: string
    label?: string
    pulse?: boolean
  }>(),
  { tone: 'mute', pulse: false },
)

const TONES: Record<string, string> = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  danger: 'var(--danger)',
  mute: 'var(--text-mute)',
}
</script>

<template>
  <span class="inline-flex items-center gap-2">
    <span
      class="relative size-2 shrink-0 rounded-full"
      :style="{ background: color ?? TONES[tone] }"
      :aria-hidden="label ? undefined : 'true'"
    >
      <span
        v-if="pulse"
        class="absolute inset-0 animate-ping rounded-full opacity-60"
        :style="{ background: color ?? TONES[tone] }"
      />
    </span>
    <span v-if="label" class="text-[0.8125rem] text-dim">{{ label }}</span>
  </span>
</template>
