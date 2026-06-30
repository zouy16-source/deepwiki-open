<script setup lang="ts">
// Nuxt UI button bound to color-mode (writes data-theme on <html>).
const colorMode = useColorMode()

function toggle() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <ClientOnly>
    <UButton
      :icon="colorMode.value === 'dark' ? 'i-lucide-sun' : 'i-lucide-moon'"
      color="neutral"
      variant="ghost"
      square
      :aria-label="`Switch to ${colorMode.value === 'dark' ? 'light' : 'dark'} mode`"
      @click="toggle"
    />
    <template #fallback>
      <div class="size-8" />
    </template>
  </ClientOnly>
</template>
