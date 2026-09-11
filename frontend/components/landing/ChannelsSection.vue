<script setup lang="ts">
import { ref } from 'vue'
import { CHANNELS, STATUS_COPY } from '~/content/channels'

const active = ref(CHANNELS[0]?.id ?? '')
</script>

<template>
  <LandingSection id="channels" eyebrow="One view, honest availability">
    <div class="flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
      <h2 class="type-h2 max-w-[14ch]">Every channel keeps its character.</h2>
      <p class="max-w-[42ch] text-sm leading-relaxed text-dim">
        One shared history does not mean pretending every platform behaves the same.
        botly respects each channel’s limits, windows and approval state.
      </p>
    </div>

    <div class="channel-accordion mt-16 flex min-h-[30rem] flex-col gap-2 lg:flex-row">
      <article
        v-for="channel in CHANNELS"
        :key="channel.id"
        class="channel-panel group relative min-h-40 cursor-pointer overflow-hidden rounded-xl border border-line bg-surface/65 p-6 backdrop-blur-xl lg:min-h-[30rem]"
        :class="active === channel.id ? 'is-active' : ''"
        tabindex="0"
        @mouseenter="active = channel.id"
        @focus="active = channel.id"
        @click="active = channel.id"
      >
        <div class="absolute inset-0 opacity-0 transition-opacity duration-700 group-hover:opacity-100" :style="{ background: `radial-gradient(circle at 50% 20%, color-mix(in srgb, ${channel.hue} 14%, transparent), transparent 62%)` }" />
        <div class="relative flex h-full flex-col">
          <div class="flex items-center justify-between gap-4">
            <span class="size-2.5 rounded-full shadow-[0_0_18px_currentColor]" :style="{ background: channel.hue, color: channel.hue }" />
            <span class="font-mono text-[0.6rem] uppercase tracking-[0.16em]" :class="channel.status === 'live' ? 'text-ok' : 'text-mute'">
              {{ STATUS_COPY[channel.status] }}
            </span>
          </div>
          <div class="mt-auto pt-14">
            <h3 class="channel-name font-display text-2xl font-medium tracking-[-0.035em]">{{ channel.name }}</h3>
            <p class="channel-note mt-4 max-w-[32ch] text-sm leading-relaxed text-dim">{{ channel.note }}</p>
          </div>
        </div>
      </article>
    </div>

    <p class="mt-7 max-w-[75ch] text-xs leading-relaxed text-mute">
      WhatsApp requires Meta business verification; Shopee requires Open Platform partner
      registration. Both remain listed as pending until the providers approve them.
    </p>
  </LandingSection>
</template>
