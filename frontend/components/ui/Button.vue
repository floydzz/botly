<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    loading?: boolean
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'primary', size: 'md', loading: false, disabled: false, type: 'button' },
)
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    class="inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors duration-state ease-house disabled:cursor-not-allowed disabled:opacity-50"
    :class="[
      size === 'sm' ? 'h-8 px-3 text-[0.8125rem]' : 'h-10 px-4 text-sm',
      variant === 'primary' && 'bg-accent text-ground hover:bg-accent-lit',
      variant === 'ghost' && 'border border-line bg-transparent text-dim hover:border-lit hover:text-body',
      variant === 'danger' && 'border border-danger/40 bg-transparent text-danger hover:bg-danger/10',
    ]"
  >
    <span v-if="loading" class="size-3 animate-spin rounded-full border border-current border-t-transparent" />
    <slot />
  </button>
</template>
