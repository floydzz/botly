<script setup lang="ts">
const auth = useAuthStore()
const route = useRoute()
const mobileOpen = ref(false)

const NAV = [
  { to: '/app/dashboard', label: 'Dashboard', icon: 'ph:squares-four-bold' },
  { to: '/app/inbox', label: 'Inbox', icon: 'ph:tray-bold' },
  { to: '/app/channels', label: 'Channels', icon: 'ph:broadcast-bold' },
  { to: '/app/bots', label: 'Bots', icon: 'ph:robot-bold' },
  { to: '/app/billing', label: 'Credits & usage', icon: 'ph:coins-bold' },
  { to: '/app/knowledge', label: 'Knowledge', icon: 'ph:books-bold' },
  { to: '/app/commerce', label: 'Commerce', icon: 'ph:storefront-bold' },
  { to: '/app/team', label: 'Team', icon: 'ph:users-three-bold' },
]

watch(() => route.fullPath, () => { mobileOpen.value = false })

function isActive(path: string) {
  return route.path === path || route.path.startsWith(`${path}/`)
}

async function signOut() {
  await auth.logout()
  await navigateTo('/login')
}
</script>

<template>
  <div class="min-h-[100dvh] bg-ground text-body">
    <div
      v-if="mobileOpen"
      class="fixed inset-0 z-40 bg-black/55 lg:hidden"
      aria-hidden="true"
      @click="mobileOpen = false"
    />

    <aside
      class="app-sidebar fixed inset-y-0 left-0 z-50 flex w-[17rem] flex-col border-r border-line bg-[#0b0d0f] px-3 py-4 transition-transform duration-300 ease-house lg:translate-x-0"
      :class="mobileOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="flex h-12 items-center justify-between px-3">
        <NuxtLink to="/app/dashboard" class="flex items-center gap-2.5 font-display text-lg font-semibold tracking-[-0.04em]">
          <span class="relative size-5 rounded-full border border-accent/60">
            <span class="absolute left-1/2 top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" />
          </span>
          botly
        </NuxtLink>
        <button class="grid size-9 place-items-center rounded-md text-dim hover:bg-raised hover:text-body lg:hidden" aria-label="Close navigation" @click="mobileOpen = false">
          <Icon name="ph:x-bold" class="size-4" />
        </button>
      </div>

      <nav class="mt-8 flex flex-1 flex-col gap-1" aria-label="Application navigation">
        <NuxtLink
          v-for="item in NAV"
          :key="item.to"
          :to="item.to"
          class="group flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors duration-state"
          :class="isActive(item.to) ? 'bg-raised text-body' : 'text-dim hover:bg-surface hover:text-body'"
        >
          <Icon :name="item.icon" class="size-[1.125rem] shrink-0" />
          {{ item.label }}
        </NuxtLink>

        <div class="my-4 border-t border-line" />

        <NuxtLink
          to="/app/settings"
          class="flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors duration-state"
          :class="isActive('/app/settings') ? 'bg-raised text-body' : 'text-dim hover:bg-surface hover:text-body'"
        >
          <Icon name="ph:gear-six-bold" class="size-[1.125rem]" />
          Settings
        </NuxtLink>
      </nav>

      <div class="border-t border-line pt-4">
        <div class="flex items-center gap-3 px-3 py-2">
          <span class="grid size-9 shrink-0 place-items-center rounded-md bg-raised font-display text-sm font-semibold text-accent">
            {{ auth.user?.name?.charAt(0).toUpperCase() || 'A' }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium">{{ auth.user?.name }}</p>
            <p class="truncate text-xs text-mute">{{ auth.user?.email }}</p>
          </div>
          <button class="grid size-9 shrink-0 place-items-center rounded-md text-mute hover:bg-raised hover:text-body" aria-label="Sign out" @click="signOut">
            <Icon name="ph:sign-out-bold" class="size-4" />
          </button>
        </div>
      </div>
    </aside>

    <div class="lg:pl-[17rem]">
      <header class="sticky top-0 z-30 flex h-16 items-center border-b border-line bg-ground/95 px-5 backdrop-blur-md lg:hidden">
        <button class="grid size-10 place-items-center rounded-md border border-line text-dim" aria-label="Open navigation" @click="mobileOpen = true">
          <Icon name="ph:list-bold" class="size-5" />
        </button>
        <span class="ml-4 font-display font-semibold">{{ NAV.find((item) => isActive(item.to))?.label || 'Settings' }}</span>
      </header>

      <main class="min-h-[100dvh]"><slot /></main>
    </div>
  </div>
</template>
