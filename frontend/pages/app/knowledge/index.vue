<script setup lang="ts">
import type { BotConfig, KnowledgeDocument } from '~/types/configuration'
import { ApiError } from '~/composables/useApi'
definePageMeta({ layout: 'app' })
useHead({ title: 'Knowledge · botly' })
const bots = ref<BotConfig[]>([]); const documents = ref<KnowledgeDocument[]>([])
const botId = ref<number | null>(null); const file = ref<File | null>(null)
const loading = ref(true); const uploading = ref(false); const error = ref(''); const notice = ref('')
const fieldClass = 'mt-2 w-full rounded-md border border-line bg-ground px-3 py-2.5 text-sm text-body focus:border-accent focus:outline-none'
async function load() { loading.value = true; error.value = ''; try { bots.value = await useApi().get<BotConfig[]>('/bots'); botId.value ??= bots.value[0]?.id ?? null; if (botId.value) documents.value = await useApi().get<KnowledgeDocument[]>(`/knowledge/documents?bot_id=${botId.value}`) } catch { error.value = 'Knowledge documents could not be loaded.' } finally { loading.value = false } }
async function upload() { if (!botId.value || !file.value) return; uploading.value = true; error.value = ''; try { const data = new FormData(); data.set('bot_id', String(botId.value)); data.set('file', file.value); await useApi().post('/knowledge/documents', data); notice.value = 'Document queued for indexing.'; file.value = null; await load() } catch (cause) { error.value = cause instanceof ApiError ? cause.detail : 'Document upload failed.' } finally { uploading.value = false } }
onMounted(load)
</script>
<template>
  <div class="mx-auto max-w-5xl px-5 py-10 md:px-8 md:py-14"><h1 class="font-display text-4xl tracking-tight">Knowledge</h1><p class="mt-3 text-dim">Upload approved business material. The RAG worker searches only the selected bot’s knowledge base.</p><p v-if="error" role="alert" class="mt-6 text-danger">{{ error }}</p><p v-if="notice" role="status" class="mt-6 text-ok">{{ notice }}</p>
    <form class="mt-8 rounded-lg border border-line bg-surface p-6" @submit.prevent="upload"><div class="grid gap-5 md:grid-cols-2"><label class="text-sm text-dim">Bot<select v-model="botId" :class="fieldClass" @change="load"><option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }}</option></select></label><label class="text-sm text-dim">Document<input accept=".txt,.md,.csv,.json,.html,.pdf,.docx" type="file" :class="fieldClass" @change="file = (($event.target as HTMLInputElement).files?.[0] || null)" /></label></div><p class="mt-3 text-xs text-mute">TXT, Markdown, CSV, JSON, HTML, PDF, and DOCX up to 25 MB. Files are stored locally in this deployment.</p><UiButton class="mt-5" type="submit" :loading="uploading" :disabled="!botId || !file">Upload and index</UiButton></form>
    <div class="mt-8 divide-y divide-line border-y border-line"><div v-for="document in documents" :key="document.id" class="py-4"><p class="font-medium">{{ document.filename }}</p><p class="mt-1 text-sm text-dim">{{ document.status }} · {{ document.chunk_count }} chunks · {{ document.embedding_model }}</p><p v-if="document.error" class="mt-1 text-sm text-danger">{{ document.error }}</p></div><p v-if="!loading && !documents.length" class="py-8 text-sm text-dim">No documents for this bot.</p></div></div>
</template>
