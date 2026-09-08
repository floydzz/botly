<script setup lang="ts">
defineProps<{
  label: string
  modelValue: string
  type?: string
  placeholder?: string
  error?: string | null
  hint?: string
  autocomplete?: string
  required?: boolean
}>()
defineEmits<{ 'update:modelValue': [string] }>()

// useId, not a random string: a random id differs between the server render
// and the client one, and Vue reports that as a hydration mismatch.
const id = useId()
</script>

<template>
  <div class="flex flex-col gap-2">
    <label :for="id" class="type-label">{{ label }}</label>
    <input
      :id="id"
      :type="type ?? 'text'"
      :value="modelValue"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      :required="required"
      :aria-invalid="Boolean(error)"
      :aria-describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined"
      class="h-10 rounded-md border bg-surface px-3 text-sm text-body placeholder:text-mute transition-colors duration-state ease-house focus:border-accent"
      :class="error ? 'border-danger' : 'border-line hover:border-lit'"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p v-if="error" :id="`${id}-error`" class="text-[0.8125rem] text-danger">{{ error }}</p>
    <p v-else-if="hint" :id="`${id}-hint`" class="text-[0.8125rem] text-mute">{{ hint }}</p>
  </div>
</template>
