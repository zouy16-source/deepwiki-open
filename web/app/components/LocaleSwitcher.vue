<script setup lang="ts">
// Replaces the custom LanguageContext. Locales come from nuxt.config i18n.
const { locale, locales, setLocale } = useI18n()

async function onChange(event: Event) {
  const code = (event.target as HTMLSelectElement).value
  await setLocale(code as typeof locale.value)
}
</script>

<template>
  <select
    :value="locale"
    class="input-japanese text-sm bg-[var(--card-bg)] text-[var(--foreground)]"
    @change="onChange"
  >
    <option v-for="l in locales" :key="l.code" :value="l.code">
      {{ l.name }}
    </option>
  </select>
</template>
