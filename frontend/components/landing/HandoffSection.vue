<script setup lang="ts">
import { computed, ref } from 'vue'

const SCENARIOS = [
  { customer: 'i want a refund', reason: 'Money or refund intent', reply: 'A person has this now. I’ve included your order and delivery history so you won’t need to repeat it.' },
  { customer: 'can i speak to someone?', reason: 'Customer requested a person', reply: 'Yes. I’ve handed this conversation over with the context attached.' },
  { customer: 'the tracking still has not changed', reason: 'Repeated unresolved question', reply: 'I can’t verify the next scan, so I’m sending this to the team instead of guessing.' },
]

const selected = ref(0)
const scenario = computed(() => SCENARIOS[selected.value] ?? SCENARIOS[0]!)
</script>

<template>
  <LandingSection eyebrow="A deliberate handoff">
    <div class="grid gap-14 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
      <div>
        <h2 class="type-h2 max-w-[14ch]">The best automated answer is sometimes no answer.</h2>
        <p class="type-lead mt-8 max-w-[48ch]">
          Requests for a person, anything involving money, repeated uncertainty and failed
          tools all stop the bot. The handoff includes the reason and the conversation that led there.
        </p>

        <div class="mt-10 flex gap-2" role="tablist" aria-label="Handoff examples">
          <button
            v-for="(_, index) in SCENARIOS"
            :key="index"
            class="h-1.5 rounded-full transition-all duration-500"
            :class="selected === index ? 'w-12 bg-accent' : 'w-6 bg-line hover:bg-lit'"
            :aria-label="`Show handoff example ${index + 1}`"
            :aria-selected="selected === index"
            role="tab"
            @click="selected = index"
          />
        </div>
      </div>

      <div class="inbox-window relative overflow-hidden rounded-[1.75rem] border border-line bg-surface/90 p-4 shadow-[0_30px_100px_rgba(0,0,0,0.35)] backdrop-blur-2xl md:p-6">
        <div class="flex items-center gap-3 border-b border-line pb-4">
          <span class="grid size-9 place-items-center rounded-lg bg-raised font-display text-sm">S</span>
          <div>
            <p class="text-sm font-medium">Siti N.</p>
            <p class="font-mono text-[0.6rem] text-mute">Telegram · order 88213441</p>
          </div>
          <span class="ml-auto size-2 rounded-full bg-accent shadow-[0_0_16px_var(--accent)]" />
        </div>

        <Transition name="scenario" mode="out-in">
          <div :key="selected" class="min-h-[24rem] pt-8">
            <div class="max-w-[82%] rounded-xl rounded-bl-sm bg-raised px-4 py-3 text-sm">{{ scenario.customer }}</div>
            <div class="my-6 flex items-center gap-3">
              <span class="h-px flex-1 bg-line" />
              <span class="font-mono text-[0.58rem] uppercase tracking-[0.16em] text-accent">handed to a person</span>
              <span class="h-px flex-1 bg-line" />
            </div>
            <div class="rounded-xl border border-accent/25 bg-accent-dim p-4">
              <p class="font-mono text-[0.6rem] uppercase tracking-[0.14em] text-accent">Reason</p>
              <p class="mt-2 text-sm text-body">{{ scenario.reason }}</p>
            </div>
            <div class="ml-auto mt-5 max-w-[88%] rounded-xl rounded-br-sm border border-line px-4 py-3 text-sm leading-relaxed text-dim">
              <span class="mb-2 block font-mono text-[0.58rem] uppercase tracking-[0.14em] text-mute">botly</span>
              {{ scenario.reply }}
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </LandingSection>
</template>
