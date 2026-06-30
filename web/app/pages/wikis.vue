<script setup lang="ts">
// Generated wiki docs. Sidebar/navbar come from the `home` layout. "查看" links
// straight to the wiki detail route (/{owner}/{repo}) — no iframe.
definePageMeta({ layout: 'home' })
</script>

<template>
  <div class="h-full">
    <WikiDocList class="h-full" />
  </div>
</template>
