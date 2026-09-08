<script setup lang="ts">
const STAGES = [
  {
    name: 'Ingress',
    body: 'A webhook arrives, gets its signature checked against the raw bytes, is deduplicated and stored, and is acknowledged in under 100ms. Providers retry aggressively, and a slow acknowledgement is a second reply to your customer.',
  },
  {
    name: 'Brain',
    body: 'The question is read, and any fact it needs is fetched from a tool — your order record, your shipping status. Nothing is inferred. If a tool cannot answer, the conversation goes to you.',
  },
  {
    name: 'Dispatcher',
    body: 'The reply is chunked to the channel’s own limit, rate-limited against the provider’s quota, and checked against the channel’s session-window rules before a single character is sent.',
  },
  {
    name: 'Inbox',
    body: 'Everything lands in one thread per customer, whichever platform they used — with what the bot already told them, visibly labelled as the bot, so you never contradict it.',
  },
]
</script>

<template>
  <LandingSection id="how" eyebrow="How it works">
    <h2 class="type-h2 max-w-[18ch]">Four stages, and you can see all of them.</h2>

    <ol class="mt-12 grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-2">
      <li v-for="(stage, index) in STAGES" :key="stage.name" class="bg-surface/80 p-6 backdrop-blur-sm">
        <p class="type-label mb-3">{{ String(index + 1).padStart(2, '0') }} — {{ stage.name }}</p>
        <p class="max-w-measure text-sm text-dim">{{ stage.body }}</p>
      </li>
    </ol>
  </LandingSection>
</template>
