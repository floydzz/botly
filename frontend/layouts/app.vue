<script setup lang="ts">
const auth = useAuthStore()
const route = useRoute()

async function signOut() {
  await auth.logout()
  await navigateTo('/login')
}

const NAV = [
  { to: '/app/inbox', label: 'Inbox' },
  { to: '/app/bots', label: 'Bots' },
  { to: '/app/channels', label: 'Channels' },
]
</script>

<template>
  <div class="flex h-screen flex-col bg-ground text-body">
    <header class="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
      <div class="flex items-center gap-8">
        <NuxtLink to="/app/inbox" class="font-display text-sm font-semibold tracking-tight">botly</NuxtLink>
        <nav class="flex items-center gap-1">
          <NuxtLink
            v-for="item in NAV"
            :key="item.to"
            :to="item.to"
            class="rounded-sm px-3 py-1.5 text-[0.8125rem] transition-colors duration-state ease-house"
            :class="route.path.startsWith(item.to) ? 'bg-raised text-body' : 'text-dim hover:text-body'"
          >
            {{ item.label }}
          </NuxtLink>
        </nav>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-[0.8125rem] text-mute">{{ auth.user?.name }}</span>
        <UiButton variant="ghost" size="sm" @click="signOut">Sign out</UiButton>
      </div>
    </header>

    <div class="min-h-0 flex-1">
      <slot />
    </div>
  </div>
</template>
