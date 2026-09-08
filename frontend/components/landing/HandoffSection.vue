<script setup lang="ts">
const TRIGGERS = [
  'The customer asks for a person, in any of three languages',
  'Anything shaped like money — a refund, a chargeback, compensation',
  'The bot has answered the same unresolved question too many times',
  'A tool failed, so the honest answer is “I cannot check that”',
]
</script>

<template>
  <LandingSection eyebrow="The handoff">
    <h2 class="type-h2 max-w-[20ch]">The bot knows when to stop talking.</h2>

    <div class="mt-12 grid gap-12 lg:grid-cols-2">
      <div>
        <p class="type-lead max-w-measure">
          Escalation is not a fallback for when things break. It is a designed path with
          named triggers, and every one of them writes down <em>why</em> — so the person
          picking the conversation up does not spend their first minute working out what
          happened.
        </p>

        <ul class="mt-8 flex flex-col gap-3">
          <li v-for="trigger in TRIGGERS" :key="trigger" class="flex gap-3 text-sm text-dim">
            <span class="mt-2 size-1.5 shrink-0 rounded-full bg-accent" />
            {{ trigger }}
          </li>
        </ul>
      </div>

      <!-- A fragment of the real inbox, not a stock screenshot. -->
      <div class="rounded-lg border border-line bg-surface/80 p-5 backdrop-blur-sm">
        <div class="flex items-center gap-3 border-b border-line pb-4">
          <span class="size-2 rounded-full" style="background: var(--channel-telegram)" />
          <span class="text-sm font-medium">Siti</span>
          <span class="font-mono text-[0.6875rem] text-mute">88213441</span>
          <span class="type-label ml-auto rounded-sm border border-accent/40 px-2 py-0.5 text-accent">
            Needs a person
          </span>
        </div>

        <div class="mt-4 rounded-md border border-accent/30 bg-accent-dim px-4 py-3">
          <p class="type-label mb-1 text-accent">Why it escalated</p>
          <p class="text-[0.8125rem] text-body">the customer raised money or a refund</p>
        </div>

        <div class="mt-5 flex flex-col gap-3">
          <div class="max-w-[85%] rounded-md rounded-bl-sm bg-raised px-3 py-2 text-[0.8125rem]">
            so where is my parcel
          </div>
          <div class="ml-auto max-w-[85%] rounded-md rounded-br-sm border border-line px-3 py-2 text-[0.8125rem] text-dim">
            <span class="type-label mb-1 block">Bot</span>
            It left the Klang hub on Tuesday and is out for delivery today.
          </div>
          <div class="max-w-[85%] rounded-md rounded-bl-sm bg-raised px-3 py-2 text-[0.8125rem]">
            i want a refund
          </div>
        </div>
      </div>
    </div>
  </LandingSection>
</template>
