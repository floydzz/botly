<script setup lang="ts">
defineProps<{ eyebrow?: string; id?: string }>()
</script>

<template>
  <section :id="id" class="reveal mx-auto max-w-shell px-6 py-24 md:py-32">
    <p v-if="eyebrow" class="type-label mb-6">{{ eyebrow }}</p>
    <slot />
  </section>
</template>
