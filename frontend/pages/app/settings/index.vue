<script setup lang="ts">
definePageMeta({ layout: 'app' })
useHead({ title: 'Settings · botly' })
</script>

<template>
  <AppPlannedPage
    title="Settings"
    description="Update your profile, brand details and account security preferences."
    icon="ph:gear-six-bold"
    next-step="Profile, brand and password endpoints need to be added before these settings can be edited safely."
  />
</template>
