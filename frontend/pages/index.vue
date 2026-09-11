<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

import { prefersReducedMotion } from '~/composables/useDeviceTier'
import { useScrollMotion, type ScrollMotion } from '~/composables/useScrollMotion'
import { sceneHandle } from '~/composables/useSceneHandle'

definePageMeta({ layout: 'marketing' })

useHead({
  title: 'botly — one inbox for every channel you sell on',
  meta: [
    {
      name: 'description',
      content:
        'botly answers your customers on Telegram, WhatsApp and Shopee from your real order data, and hands the hard conversations to a person before they become refund disputes.',
    },
  ],
})

let motion: ScrollMotion | null = null

onMounted(() => {
  // After hydration, and after the canvas has had its chance to mount, so the
  // scene is never on the critical path and never the LCP element.
  requestAnimationFrame(() => {
    motion = useScrollMotion(sceneHandle.value, {
      reducedMotion: prefersReducedMotion(),
    })
  })
})

onBeforeUnmount(() => motion?.destroy())
</script>

<template>
  <div>
    <LandingHeroSection />
    <LandingProblemSection />
    <LandingChannelsSection />
    <LandingHowItWorksSection />
    <LandingHandoffSection />
    <LandingGuaranteeSection />
    <LandingRequestAccessSection />
  </div>
</template>
