<script setup lang="ts">
import type { BotConfig, BotWorker, ModelOption } from '~/types/configuration'
import { ApiError } from '~/composables/useApi'

definePageMeta({ layout: 'app' })
useHead({ title: 'Bots · botly' })
const bots = ref<BotConfig[]>([])
const models = ref<ModelOption[]>([])
const brands = ref<{ id: number; name: string }[]>([])
const loading = ref(true)
const saving = ref<number | null>(null)
const error = ref('')
const notice = ref('')
const newName = ref('')
const brandId = ref<number | null>(null)
const workers = ref<Record<number, BotWorker[]>>({})
const fieldClass = 'mt-2 w-full rounded-md border border-line bg-ground px-3 py-2.5 text-sm text-body focus:border-accent focus:outline-none'

async function load() {
  error.value = ''; loading.value = true
  try {
    [bots.value, models.value, brands.value] = await Promise.all([
      useApi().get<BotConfig[]>('/bots'), useApi().get<ModelOption[]>('/models'),
      useApi().get<{ id: number; name: string }[]>('/brands'),
    ])
    brandId.value ??= brands.value[0]?.id ?? null
    await Promise.all(bots.value.map(async bot => { workers.value[bot.id] = await useApi().get<BotWorker[]>(`/bots/${bot.id}/workers`) }))
  } catch { error.value = 'Bot configuration could not be loaded.' }
  finally { loading.value = false }
}

async function save(bot: BotConfig) {
  saving.value = bot.id; error.value = ''; notice.value = ''
  try {
    await useApi().patch(`/bots/${bot.id}`, { name: bot.name, persona: bot.persona, llm_model_id: bot.llm_model_id, escalation_max_bot_turns: bot.escalation_max_bot_turns, tool_write_mode: bot.tool_write_mode, auditor_enabled: bot.auditor_enabled })
    notice.value = `${bot.name} saved.`
  } catch (cause) { error.value = cause instanceof ApiError ? cause.detail : 'Could not save bot.' }
  finally { saving.value = null }
}

async function create() {
  saving.value = 0; error.value = ''; notice.value = ''
  try {
    const bot = await useApi().post<BotConfig>('/bots', { name: newName.value, brand_id: brandId.value })
    bots.value.push(bot); newName.value = ''; notice.value = 'Bot created. Choose its model below.'
  } catch (cause) { error.value = cause instanceof ApiError ? cause.detail : 'Could not create bot.' }
  finally { saving.value = null }
}
async function toggleWorker(bot: BotConfig, worker: BotWorker) { await useApi().put(`/bots/${bot.id}/workers/${worker.key}`, { enabled: worker.enabled, config: worker.config }) }
onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-5xl px-5 py-10 md:px-8 md:py-14">
    <h1 class="font-display text-4xl tracking-tight">Bots</h1>
    <p class="mt-3 text-dim">Choose a model and give each bot its own voice. All bots share your merchant’s credits.</p>
    <p v-if="error" role="alert" class="mt-6 text-danger">{{ error }} <button class="underline" @click="load">Reload</button></p>
    <p v-if="notice" role="status" class="mt-6 text-ok">{{ notice }}</p>
    <p v-if="loading" class="mt-8 text-dim">Loading bots…</p>
    <template v-else>
      <form class="mt-8 flex flex-wrap items-end gap-4 border-b border-line pb-8" @submit.prevent="create">
        <label class="min-w-48 flex-1 text-sm text-dim">New bot name<input v-model="newName" required maxlength="255" :class="fieldClass" /></label>
        <label class="min-w-48 flex-1 text-sm text-dim">Brand<select v-model="brandId" required :class="fieldClass"><option v-for="brand in brands" :key="brand.id" :value="brand.id">{{ brand.name }}</option></select></label>
        <UiButton type="submit" :loading="saving === 0" :disabled="saving !== null || !brandId">Create bot</UiButton>
      </form>
      <p v-if="!models.length" class="mt-6 rounded-md border border-line p-4 text-sm text-dim">No models are available yet. Your platform operator needs to publish model pricing and configure a provider.</p>
      <form v-for="bot in bots" :key="bot.id" class="mt-8 rounded-lg border border-line bg-surface p-6" @submit.prevent="save(bot)">
        <div class="grid gap-5 md:grid-cols-2">
          <label class="text-sm text-dim">Bot name<input v-model="bot.name" required maxlength="255" :class="fieldClass" /></label>
          <label class="text-sm text-dim">Model<select v-model="bot.llm_model_id" :class="fieldClass">
            <option :value="null">No paid model selected</option>
            <option v-if="bot.llm_model_id && !models.some(m => m.id === bot.llm_model_id)" :value="bot.llm_model_id" disabled>Previously selected model is unavailable</option>
            <option v-for="model in models" :key="model.id" :value="model.id" :disabled="!model.available">{{ model.provider }} · {{ model.name }}{{ model.available ? '' : ' (unavailable)' }}</option>
          </select></label>
        </div>
        <p v-if="models.find(m => m.id === bot.llm_model_id)" class="mt-3 text-xs text-dim">Per 1M tokens: {{ Number(models.find(m => m.id === bot.llm_model_id)?.input_credits_per_million).toLocaleString() }} input credits · {{ Number(models.find(m => m.id === bot.llm_model_id)?.output_credits_per_million).toLocaleString() }} output credits.</p>
        <label class="mt-5 block text-sm text-dim">Persona and instructions<textarea v-model="bot.persona" rows="5" maxlength="12000" :class="fieldClass" /></label>
        <label class="mt-5 block text-sm text-dim">Tool writes<select v-model="bot.tool_write_mode" :class="fieldClass"><option value="confirm_customer">Ask customer before action</option><option value="auto_execute">Automatically execute actions</option></select></label>
        <label class="mt-4 flex items-center gap-3 text-sm text-dim"><input v-model="bot.auditor_enabled" type="checkbox" /> Enable knowledge auditor</label>
        <p class="mt-1 text-xs text-mute">The auditor blocks unsupported business-specific claims. General questions can still be answered.</p>
        <div v-if="workers[bot.id]?.length" class="mt-5"><p class="text-sm text-dim">Workers</p><label v-for="worker in workers[bot.id]" :key="worker.key" class="mt-2 flex items-center gap-3 text-sm"><input v-model="worker.enabled" type="checkbox" @change="toggleWorker(bot, worker)" /><span>{{ worker.name }}</span><span class="text-dim">{{ worker.description }}</span></label></div>
        <div class="mt-5 flex flex-wrap items-end justify-between gap-4">
          <label class="text-sm text-dim">Handoff at bot turn<input v-model.number="bot.escalation_max_bot_turns" type="number" min="1" max="50" required :class="fieldClass" /></label>
          <UiButton type="submit" :loading="saving === bot.id" :disabled="saving !== null">Save bot</UiButton>
        </div>
      </form>
    </template>
  </div>
</template>
