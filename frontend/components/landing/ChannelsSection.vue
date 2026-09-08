<script setup lang="ts">
import { CHANNELS, STATUS_COPY } from '~/content/channels'
</script>

<template>
  <LandingSection id="channels" eyebrow="Channels">
    <h2 class="type-h2 max-w-[18ch]">What actually works today.</h2>

    <p class="type-lead mt-6 max-w-measure">
      Two of these are waiting on someone else. We would rather say so here than let you
      find out after you have signed up.
    </p>

    <ul class="mt-12 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface/70 backdrop-blur-sm">
      <li
        v-for="channel in CHANNELS"
        :key="channel.id"
        class="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between sm:gap-8"
      >
        <div class="flex items-start gap-4">
          <span class="mt-1.5 size-2.5 shrink-0 rounded-full" :style="{ background: channel.hue }" />
          <div>
            <h3 class="font-display text-base font-semibold">{{ channel.name }}</h3>
            <p class="mt-1 max-w-measure text-[0.8125rem] text-dim">{{ channel.note }}</p>
          </div>
        </div>

        <span
          class="type-label shrink-0 rounded-sm border px-2 py-1"
          :class="
            channel.status === 'live'
              ? 'border-ok/40 text-ok'
              : 'border-line text-mute'
          "
        >
          {{ STATUS_COPY[channel.status] }}
        </span>
      </li>
    </ul>

    <p class="mt-6 max-w-measure text-[0.8125rem] text-mute">
      WhatsApp needs Meta business verification; Shopee needs Open Platform partner
      registration. Both are filed processes measured in weeks, and neither is something
      we can hurry. When one clears, it appears here as available and not before.
    </p>
  </LandingSection>
</template>
