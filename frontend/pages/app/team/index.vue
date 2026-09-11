<script setup lang="ts">
definePageMeta({ layout: 'app' })
useHead({ title: 'Team · botly' })
</script>

<template>
  <AppPlannedPage
    title="Team"
    description="Manage the people who can see, claim and answer conversations for this merchant."
    icon="ph:users-three-bold"
    next-step="Invitations and role controls need new APIs. Conversation assignment already has the database field required for the first team workflow."
  />
</template>
