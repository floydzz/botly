<script setup lang="ts">
const QUESTIONS = [
  { text: 'Where is my parcel?', lang: 'EN', x: '8%', delay: '0s' },
  { text: 'Bila sampai?', lang: 'BM', x: '55%', delay: '-1.4s' },
  { text: '有货吗?', lang: 'ZH', x: '27%', delay: '-2.8s' },
  { text: 'Can I change the address?', lang: 'EN', x: '68%', delay: '-4.2s' },
  { text: 'I want a refund', lang: 'EN', x: '16%', delay: '-5.6s' },
]

const STATEMENT = 'Three inboxes create three versions of the same customer. botly brings the context back together before anyone has to repeat themselves.'.split(' ')
</script>

<template>
  <LandingSection eyebrow="The noise before the signal">
    <div class="grid gap-16 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
      <div class="lg:sticky lg:top-32">
        <h2 class="type-h2 max-w-[15ch]">
          Support <span class="inline-signal" aria-hidden="true"><i /><i /><i /></span>
          should not feel like chasing tabs.
        </h2>
        <p class="mt-7 max-w-[43ch] text-base leading-relaxed text-dim">
          The same six questions arrive all day in three languages. Their answers already
          exist inside your order records; the hard part is getting every channel to read them.
        </p>
      </div>

      <div>
        <p class="scrub-statement max-w-[18ch] font-display text-[clamp(2rem,4.2vw,4.6rem)] font-medium leading-[1.04] tracking-[-0.045em]">
          <span v-for="(word, index) in STATEMENT" :key="`${word}-${index}`" class="scrub-word inline-block">{{ word }}&nbsp;</span>
        </p>

        <div class="question-field relative mt-20 h-[27rem] overflow-hidden rounded-[2rem] border border-line/70">
          <div class="question-orbit absolute left-1/2 top-1/2 size-[19rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-line/70" />
          <div class="question-core absolute left-1/2 top-1/2 grid size-24 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full">
            <span class="font-display text-sm font-medium">one thread</span>
          </div>
          <div
            v-for="question in QUESTIONS"
            :key="question.text"
            class="question-chip absolute flex items-center gap-3 rounded-md border border-line bg-surface/80 px-4 py-3 backdrop-blur-xl"
            :style="{ left: question.x, animationDelay: question.delay }"
          >
            <span class="font-mono text-[0.58rem] text-accent">{{ question.lang }}</span>
            <span class="text-sm text-body">{{ question.text }}</span>
          </div>
        </div>
      </div>
    </div>
  </LandingSection>
</template>
