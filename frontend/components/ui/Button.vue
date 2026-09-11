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
    class="inline-flex items-center justify-center gap-2 rounded-md font-medium transition duration-state ease-house disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]"
    :class="[
      size === 'sm' ? 'h-9 px-4 text-[0.8125rem]' : 'h-12 px-6 text-sm',
      variant === 'primary' && 'bg-accent text-ground shadow-[0_12px_40px_rgba(241,164,76,0.15)] hover:-translate-y-0.5 hover:bg-accent-lit',
      variant === 'ghost' && 'border border-line bg-transparent text-dim hover:border-lit hover:text-body',
      variant === 'danger' && 'border border-danger/40 bg-transparent text-danger hover:bg-danger/10',
    ]"
  >
    <span v-if="loading" class="size-3 animate-spin rounded-full border border-current border-t-transparent" />
    <slot />
  </button>
</template>
