<script setup lang="ts">
const STAGES = [
  { name: 'Receive', marker: '01', body: 'The webhook is verified against its raw bytes, deduplicated, stored and acknowledged in under 100ms.', detail: 'Fast acknowledgement prevents a provider retry from becoming a duplicate reply.' },
  { name: 'Understand', marker: '02', body: 'The question is read and every needed fact is fetched from your actual order data.', detail: 'The model chooses the words. Your systems supply the truth.' },
  { name: 'Respect', marker: '03', body: 'The reply is shaped around the channel’s own message limit, rate quota and session window.', detail: 'One brain, without flattening the rules of the places where customers speak.' },
  { name: 'Remember', marker: '04', body: 'Every exchange lands in one customer thread with the bot’s replies clearly identified.', detail: 'When a person steps in, the full story is already there.' },
]
</script>

<template>
  <LandingSection id="how" eyebrow="From notification to resolution">
    <div class="grid gap-14 lg:grid-cols-[0.7fr_1.3fr]">
      <div class="how-heading lg:sticky lg:top-32 lg:h-fit">
        <h2 class="type-h2 max-w-[12ch]">One message. Four careful decisions.</h2>
        <p class="mt-6 max-w-[34ch] text-sm leading-relaxed text-dim">
          Watch the system narrow uncertainty without hiding what happened in the middle.
        </p>
      </div>

      <div class="stack-list relative pb-24">
        <article
          v-for="stage in STAGES"
          :key="stage.name"
          class="stack-card sticky mb-8 min-h-[24rem] overflow-hidden rounded-[1.5rem] border border-line bg-[#111318]/95 p-7 shadow-[0_-24px_80px_rgba(2,3,5,0.35)] backdrop-blur-xl md:p-10"
          :style="{ top: `calc(7rem + ${Number(stage.marker) * 0.8}rem)` }"
        >
          <div class="absolute -right-8 -top-16 font-display text-[13rem] font-semibold leading-none text-white/[0.025]">{{ stage.marker }}</div>
          <div class="relative flex h-full min-h-[19rem] flex-col justify-between">
            <div class="flex items-start justify-between">
              <p class="font-mono text-xs text-accent">{{ stage.marker }}</p>
              <span class="h-px w-20 bg-line" />
            </div>
            <div>
              <h3 class="font-display text-[clamp(2.4rem,5vw,5rem)] font-medium leading-none tracking-[-0.05em]">{{ stage.name }}</h3>
              <div class="mt-7 grid gap-4 md:grid-cols-2 md:gap-10">
                <p class="text-base leading-relaxed text-body">{{ stage.body }}</p>
                <p class="text-sm leading-relaxed text-dim">{{ stage.detail }}</p>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>
  </LandingSection>
</template>
