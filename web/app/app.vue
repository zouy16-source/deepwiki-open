<script setup lang="ts">
const { locale } = useI18n()

// Mirror the old Next.js <head>: preconnect + Google Fonts, and keep <html lang>
// in sync with the active locale.
useHead({
  htmlAttrs: { lang: locale },
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Geist+Mono&family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@400;500;700&display=swap',
    },
  ],
})

useSeoMeta({
  title: 'Deepwiki Open Source',
  description: 'AI-powered documentation for code repositories',
})
</script>

<template>
  <!-- UApp provides @nuxt/ui's toast/overlay/tooltip context. -->
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
