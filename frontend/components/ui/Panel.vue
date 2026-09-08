<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string; tight?: boolean }>()
</script>

<template>
  <section class="rounded-lg border border-line bg-surface" :class="tight ? 'p-4' : 'p-6'">
    <header v-if="title" class="mb-4 flex flex-col gap-1">
      <h2 class="type-h3 text-body">{{ title }}</h2>
      <p v-if="subtitle" class="text-[0.8125rem] text-dim">{{ subtitle }}</p>
    </header>
    <slot />
  </section>
</template>
