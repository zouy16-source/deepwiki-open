<script setup lang="ts">
// Replaces next-themes' useTheme(). color-mode writes data-theme on <html>.
const colorMode = useColorMode()

function toggle() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <button
    type="button"
    :aria-label="`Switch to ${colorMode.value === 'dark' ? 'light' : 'dark'} mode`"
    class="p-2 rounded-lg border border-[var(--border-color)] text-[var(--foreground)] hover:bg-[var(--background)] transition-colors"
    @click="toggle"
  >
    <ClientOnly>
      <Icon :name="colorMode.value === 'dark' ? 'fa6-solid:sun' : 'fa6-solid:moon'" class="text-base" />
      <template #fallback>
        <span class="inline-block w-4 h-4" />
      </template>
    </ClientOnly>
  </button>
</template>
