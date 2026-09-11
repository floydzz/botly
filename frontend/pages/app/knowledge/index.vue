<script setup lang="ts">
definePageMeta({ layout: 'app' })
useHead({ title: 'Knowledge · botly' })
</script>

<template>
  <AppPlannedPage
    title="Knowledge"
    description="Manage the policies, product information and answers that support bots are allowed to use."
    icon="ph:books-bold"
    next-step="Knowledge documents, chunks, ingestion jobs and retrieval APIs still need database migrations before this workspace can accept content."
  />
</template>
