<script setup lang="ts">
const QUESTIONS = [
  'Where is my parcel?',
  'Bila sampai?',
  'Is this still available?',
  '有货吗?',
  'Can I change the address?',
  'I want a refund',
]
</script>

<template>
  <LandingSection eyebrow="The problem">
    <h2 class="type-h2 max-w-[18ch]">The same questions, all day, on every platform you sell on.</h2>

    <p class="type-lead mt-6 max-w-measure">
      A seller running Telegram, WhatsApp and a Shopee shop is running three inboxes with
      three notification sounds and no shared history. The questions are nearly all the
      same, and nearly all of them have an answer sitting in an order record.
    </p>

    <ul class="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <li
        v-for="question in QUESTIONS"
        :key="question"
        class="rounded-md border border-line bg-surface/60 px-4 py-3 text-sm text-dim backdrop-blur-sm"
      >
        “{{ question }}”
      </li>
    </ul>
  </LandingSection>
</template>
