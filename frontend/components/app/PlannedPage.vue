<script setup lang="ts">
defineProps<{
  title: string
  description: string
  icon: string
  nextStep: string
}>()
</script>

<template>
  <div class="mx-auto max-w-[1180px] px-5 py-10 md:px-8 md:py-14 xl:px-12">
    <header class="max-w-2xl">
      <h1 class="font-display text-3xl font-medium tracking-[-0.04em] md:text-4xl">{{ title }}</h1>
      <p class="mt-3 text-sm leading-relaxed text-dim md:text-base">{{ description }}</p>
    </header>

    <section class="mt-12 grid min-h-[26rem] place-items-center rounded-lg border border-line bg-surface/55 px-6 text-center">
      <div class="max-w-md">
        <span class="mx-auto grid size-12 place-items-center rounded-lg border border-line bg-raised text-accent">
          <Icon :name="icon" class="size-6" />
        </span>
        <h2 class="mt-6 font-display text-xl font-medium">This workspace is ready for its data flow.</h2>
        <p class="mt-3 text-sm leading-relaxed text-dim">{{ nextStep }}</p>
        <NuxtLink to="/app/dashboard" class="mt-7 inline-flex h-10 items-center justify-center gap-2 rounded-md border border-line px-4 text-sm text-body transition-colors hover:border-lit hover:bg-raised">
          <Icon name="ph:arrow-left-bold" class="size-4" />
          Back to dashboard
        </NuxtLink>
      </div>
    </section>
  </div>
</template>
