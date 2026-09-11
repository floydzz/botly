<script setup lang="ts">
import { ref } from 'vue'

const email = ref('')
const shop = ref('')
const submitted = ref(false)

function submit() {
  const body = encodeURIComponent(`I'd like access to botly.\n\nEmail: ${email.value}\nShop: ${shop.value || '—'}\n`)
  window.location.href = `mailto:hello@botly.app?subject=${encodeURIComponent('Access request')}&body=${body}`
  submitted.value = true
}
</script>

<template>
  <LandingSection id="request-access" eyebrow="Bring the threads together">
    <div class="cta-stage relative overflow-hidden rounded-[2rem] border border-line px-6 py-16 md:px-12 md:py-24 lg:px-20">
      <div class="cta-orbit pointer-events-none absolute -right-32 -top-32 size-[34rem] rounded-full border border-accent/20" />
      <div class="relative grid gap-14 lg:grid-cols-[1fr_0.72fr] lg:items-end">
        <div>
          <h2 class="type-h2 max-w-[12ch]">One inbox is closer than it looks.</h2>
          <p class="type-lead mt-7 max-w-[47ch]">Accounts are set up by hand while botly is small. Tell us where you sell and we will map the channels and order data with you.</p>
        </div>

        <form class="flex flex-col gap-4" novalidate @submit.prevent="submit">
          <UiField v-model="email" label="Email" type="email" placeholder="you@yourshop.com" autocomplete="email" required />
          <UiField v-model="shop" label="Shop or brand" placeholder="What you sell and where" />
          <UiButton type="submit">Request access</UiButton>
          <p v-if="submitted" class="text-xs text-ok">Your mail client should have opened. If it did not, write to hello@botly.app.</p>
          <p class="mt-2 text-xs text-mute">Already have an account? <NuxtLink to="/login" class="text-body underline underline-offset-4">Sign in</NuxtLink></p>
        </form>
      </div>
    </div>
  </LandingSection>
</template>
