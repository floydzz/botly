<script setup lang="ts">
import { ApiError } from '~/composables/useApi'
definePageMeta({ layout: 'app' })
useHead({ title: 'Tools · botly' })
type Tool = { id: number; name: string; description: string; endpoint: string; method: string; input_schema: Record<string, unknown>; enabled: boolean }
const tools = ref<Tool[]>([]); const saving = ref(false); const error = ref(''); const notice = ref('')
const form = reactive({ name: '', description: '', endpoint: '', method: 'GET', inputSchema: '{}' })
const fieldClass = 'mt-2 w-full rounded-md border border-line bg-ground px-3 py-2.5 text-sm text-body focus:border-accent focus:outline-none'
async function load() { try { tools.value = await useApi().get<Tool[]>('/tools') } catch { error.value = 'Tools could not be loaded.' } }
async function add() { saving.value = true; error.value = ''; try { const input_schema = JSON.parse(form.inputSchema); await useApi().post('/tools', { name: form.name, description: form.description, endpoint: form.endpoint, method: form.method, input_schema }); notice.value = 'Tool registered.'; Object.assign(form, { name: '', description: '', endpoint: '', method: 'GET', inputSchema: '{}' }); await load() } catch (cause) { error.value = cause instanceof ApiError ? cause.detail : 'Use valid JSON for the input schema.' } finally { saving.value = false } }
onMounted(load)
</script>
<template>
  <div class="mx-auto max-w-5xl px-5 py-10 md:px-8 md:py-14"><h1 class="font-display text-4xl tracking-tight">Customer tools</h1><p class="mt-3 text-dim">Register approved HTTPS APIs for the Tools worker. Customer confirmation remains the default for write operations.</p><p v-if="error" class="mt-6 text-danger">{{ error }}</p><p v-if="notice" class="mt-6 text-ok">{{ notice }}</p>
    <form class="mt-8 rounded-lg border border-line bg-surface p-6" @submit.prevent="add"><div class="grid gap-5 md:grid-cols-2"><label class="text-sm text-dim">Name<input v-model="form.name" required maxlength="128" :class="fieldClass" /></label><label class="text-sm text-dim">Method<select v-model="form.method" :class="fieldClass"><option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option></select></label><label class="text-sm text-dim md:col-span-2">HTTPS endpoint<input v-model="form.endpoint" type="url" required placeholder="https://api.example.com/orders" :class="fieldClass" /></label><label class="text-sm text-dim md:col-span-2">Description<input v-model="form.description" maxlength="4000" :class="fieldClass" /></label><label class="text-sm text-dim md:col-span-2">Input JSON schema<textarea v-model="form.inputSchema" rows="4" :class="fieldClass" /></label></div><UiButton class="mt-5" type="submit" :loading="saving">Register tool</UiButton></form>
    <div class="mt-8 divide-y divide-line border-y border-line"><div v-for="tool in tools" :key="tool.id" class="py-4"><p class="font-medium">{{ tool.name }} <span class="text-sm text-dim">{{ tool.method }}</span></p><p class="mt-1 text-sm text-dim">{{ tool.endpoint }}</p><p class="mt-1 text-sm text-dim">{{ tool.description }}</p></div><p v-if="!tools.length" class="py-8 text-sm text-dim">No customer tools registered.</p></div></div>
</template>
