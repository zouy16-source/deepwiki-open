<script setup lang="ts">
const { t } = useI18n()
</script>

<template>
  <div class="h-screen flex flex-col bg-[var(--background)] text-[var(--foreground)]">
    <header
      class="flex items-center justify-between px-6 py-3 border-b border-[var(--border-color)] bg-[var(--card-bg)] shadow-custom"
    >
      <div class="flex items-center gap-3">
        <div class="bg-[var(--accent-primary)] p-2 rounded-lg">
          <Icon name="fa6-brands:wikipedia-w" class="text-xl text-white" />
        </div>
        <h1 class="text-lg font-bold text-[var(--accent-primary)]">
          {{ t('common.appName') }}
        </h1>
      </div>
      <div class="flex items-center gap-3">
        <LocaleSwitcher />
        <ThemeToggle />
      </div>
    </header>

    <!-- Pages manage their own scrolling (home fills height; others add overflow). -->
    <main class="flex-1 min-h-0">
      <slot />
    </main>
  </div>
</template>
