<script setup lang="ts">
defineProps<{ eyebrow?: string; id?: string }>()
</script>

<template>
  <section :id="id" class="reveal mx-auto max-w-[1440px] px-6 py-32 md:px-10 md:py-48 lg:px-14">
    <p v-if="eyebrow" class="section-eyebrow mb-8 flex items-center gap-3">
      <span class="size-1.5 rounded-full bg-accent" />{{ eyebrow }}
    </p>
    <slot />
  </section>
</template>
