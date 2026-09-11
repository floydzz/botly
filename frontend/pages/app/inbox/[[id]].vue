<script setup lang="ts">
definePageMeta({ layout: 'app' })
const route = useRoute()
const store = useInboxStore()

const selectedId = computed(() => {
  const raw = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

useHead({ title: computed(() => store.detail?.customer_name ? `${store.detail.customer_name} · Inbox · botly` : 'Inbox · botly') })

async function openSelected() {
  if (selectedId.value) await store.openConversation(selectedId.value)
  else store.clearThread()
}

onMounted(async () => {
  await store.refresh()
  await openSelected()
})

watch(selectedId, openSelected)
</script>

<template>
  <div class="grid h-[calc(100dvh-4rem)] min-h-[36rem] grid-cols-1 overflow-hidden lg:h-[100dvh] md:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] xl:grid-cols-[13rem_minmax(19rem,22rem)_minmax(0,1fr)]">
    <InboxFilterRail />
    <InboxConversationList :selected-id="selectedId" :class="selectedId ? 'hidden md:flex' : 'flex'" />
    <InboxMessageThread :class="selectedId ? 'flex' : ''" />
  </div>
</template>
