<script setup lang="ts">
// Nuxt UI select bound to vue-i18n. Locales come from nuxt.config i18n.
const { locale, locales, setLocale } = useI18n()

const items = computed(() =>
  (locales.value as Array<{ code: string; name: string }>).map((l) => ({ label: l.name, value: l.code })),
)
const model = computed({
  get: () => locale.value,
  set: (v: string) => { void setLocale(v as typeof locale.value) },
})
</script>

<template>
  <USelect
    v-model="model"
    :items="items"
    icon="i-lucide-languages"
    color="neutral"
    variant="ghost"
    :ui="{ base: 'min-w-28' }"
  />
</template>
