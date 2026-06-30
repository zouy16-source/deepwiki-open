<script setup lang="ts">
// Project list (GitLab). Sidebar/navbar come from the `home` layout.
definePageMeta({ layout: 'home' })
</script>

<template>
  <div class="h-full">
    <GitlabProjectList class="h-full" />
  </div>
</template>
