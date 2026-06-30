<script setup lang="ts">
// Dev self-check: verifies i18n, color-mode, Tailwind/CSS vars, @nuxt/ui, and the
// Nitro -> FastAPI proxy. Not part of the product UI.
const { t, locale } = useI18n()
const colorMode = useColorMode()

const proxyState = ref<'idle' | 'loading' | 'ok' | 'error'>('idle')
const proxyResult = ref('')

async function testProxy() {
  proxyState.value = 'loading'
  proxyResult.value = ''
  try {
    const data = await $fetch('/api/lang/config')
    proxyState.value = 'ok'
    proxyResult.value = JSON.stringify(data, null, 2)
  } catch (err: unknown) {
    proxyState.value = 'error'
    proxyResult.value = err instanceof Error ? err.message : String(err)
  }
}

const checks = computed(() => [
  { label: 'i18n (vue-i18n)', value: `${t('common.appName')} · locale=${locale.value}` },
  { label: 'color-mode', value: `data-theme=${colorMode.value} (preference=${colorMode.preference})` },
  { label: '@nuxt/ui + Tailwind v4', value: '本页按钮/输入来自 @nuxt/ui，配色来自 var(--*)' },
])
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-3xl mx-auto p-6 space-y-6">
      <div class="flex items-center gap-3 text-sm">
        <NuxtLink to="/" class="text-primary hover:underline">← 返回首页</NuxtLink>
        <NuxtLink to="/markdown-demo" class="text-primary hover:underline">渲染管线 Demo →</NuxtLink>
      </div>

      <UCard>
        <template #header>
          <h2 class="text-lg font-bold text-primary">基座自检 / Self-Check</h2>
        </template>
        <div class="space-y-3">
          <div v-for="c in checks" :key="c.label" class="flex items-start gap-3 text-sm">
            <UIcon name="i-fa6-solid-circle-check" class="text-secondary mt-0.5" />
            <div>
              <div class="font-medium text-default">{{ c.label }}</div>
              <div class="text-muted font-mono text-xs">{{ c.value }}</div>
            </div>
          </div>
          <div class="flex items-center gap-3 pt-2">
            <UButton color="primary" icon="i-fa6-brands-github" label="UButton" />
            <UBadge color="success" variant="soft" label="UBadge" />
            <UInput placeholder="UInput" size="sm" />
          </div>
        </div>
      </UCard>

      <UCard>
        <template #header>
          <div class="flex items-center justify-between">
            <h3 class="font-semibold text-default">BFF 代理 → FastAPI</h3>
            <UButton color="primary" :loading="proxyState === 'loading'" label="测试 /api/lang/config" @click="testProxy" />
          </div>
        </template>
        <pre
          v-if="proxyResult"
          class="text-xs font-mono p-3 rounded border border-default bg-default overflow-x-auto"
          :class="proxyState === 'error' ? 'text-error' : 'text-default'"
        >{{ proxyResult }}</pre>
        <p v-else class="text-xs text-muted">点击按钮测试 Nitro routeRules 代理到后端。</p>
      </UCard>
    </div>
  </div>
</template>
