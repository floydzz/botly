<script setup lang="ts">
import { ref } from 'vue'

/**
 * "Request access", not "Sign up".
 *
 * There is no registration endpoint, deliberately (app/api/auth.py). A sign-up
 * button leading to a login form with no way to obtain credentials is worse
 * than no button, so this form collects an email and says plainly that a
 * person will set the account up.
 */
const email = ref('')
const shop = ref('')
const submitted = ref(false)

function submit() {
  // No endpoint yet, and inventing one that silently discards the address
  // would be worse than saying so. Until there is somewhere to send it, the
  // form opens the visitor's mail client with the details filled in.
  const body = encodeURIComponent(
    `I'd like access to botly.\n\nEmail: ${email.value}\nShop: ${shop.value || '—'}\n`,
  )
  window.location.href = `mailto:hello@botly.app?subject=${encodeURIComponent('Access request')}&body=${body}`
  submitted.value = true
}
</script>

<template>
  <LandingSection id="request-access" eyebrow="Get started">
    <div class="rounded-lg border border-line bg-surface/80 p-8 backdrop-blur-sm md:p-12">
      <h2 class="type-h2 max-w-[16ch]">Request access.</h2>

      <p class="type-lead mt-6 max-w-measure">
        Accounts are set up by hand while we are small — we want to see your channels and
        your order data before we tell you it will work. Leave an address and we will come
        back to you.
      </p>

      <form class="mt-10 flex max-w-lg flex-col gap-5" novalidate @submit.prevent="submit">
        <UiField
          v-model="email"
          label="Email"
          type="email"
          placeholder="you@yourshop.com"
          autocomplete="email"
          required
        />
        <UiField
          v-model="shop"
          label="Shop or brand"
          placeholder="Optional — what you sell and where"
        />

        <div class="flex flex-wrap items-center gap-4">
          <UiButton type="submit">Request access</UiButton>
          <p v-if="submitted" class="text-[0.8125rem] text-ok">
            Your mail client should have opened. If it did not, write to hello@botly.app.
          </p>
        </div>
      </form>

      <p class="mt-8 border-t border-line pt-6 text-[0.8125rem] text-mute">
        Already have an account?
        <NuxtLink to="/login" class="text-accent underline underline-offset-4 hover:text-accent-lit">
          Sign in
        </NuxtLink>
      </p>
    </div>
  </LandingSection>
</template>
