<script setup lang="ts">
import { ApiError } from '~/composables/useApi'

definePageMeta({ layout: 'bare' })
useHead({ title: 'Sign in · botly' })

const auth = useAuthStore()
const route = useRoute()

const email = ref('')
const password = ref('')
const error = ref<string | null>(null)
const submitting = ref(false)

async function submit() {
  error.value = null
  submitting.value = true
  try {
    await auth.login(email.value, password.value)
    // The return path the guard stashed, so an agent who followed a link to a
    // conversation lands on that conversation rather than a generic inbox.
    const next = typeof route.query.next === 'string' ? route.query.next : '/app/inbox'
    await navigateTo(next)
  } catch (cause) {
    error.value =
      cause instanceof ApiError && cause.status === 401
        ? 'That email and password do not match an account.'
        : 'Sign-in could not be completed. Try again in a moment.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-ground px-6">
    <div class="w-full max-w-[26rem]">
      <NuxtLink to="/" class="type-label mb-10 inline-block hover:text-accent">← botly</NuxtLink>

      <h1 class="type-h2 mb-2">Sign in</h1>
      <p class="mb-8 text-sm text-dim">The seller inbox for your bots.</p>

      <form class="flex flex-col gap-5" novalidate @submit.prevent="submit">
        <UiField
          v-model="email"
          label="Email"
          type="email"
          autocomplete="username"
          placeholder="you@yourshop.com"
          required
        />
        <UiField
          v-model="password"
          label="Password"
          type="password"
          autocomplete="current-password"
          required
        />

        <p v-if="error" role="alert" class="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[0.8125rem] text-danger">
          {{ error }}
        </p>

        <UiButton type="submit" :loading="submitting">Sign in</UiButton>
      </form>

      <!--
        No "create an account" link, and that is deliberate rather than an
        omission: there is no registration endpoint. A sign-up button leading
        to a form with no way to obtain credentials is worse than no button.
      -->
      <p class="mt-8 border-t border-line pt-6 text-[0.8125rem] text-mute">
        Accounts are created for you. If you do not have one yet,
        <NuxtLink to="/#request-access" class="text-accent underline underline-offset-4 hover:text-accent-lit"
          >request access</NuxtLink
        >
        and we will be in touch.
      </p>
    </div>
  </main>
</template>
