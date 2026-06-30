// The Python FastAPI backend. Mirrors SERVER_BASE_URL used by the old Next.js app.
const SERVER_BASE_URL = process.env.SERVER_BASE_URL || 'http://localhost:8001'
const GITLAB_BASE = (process.env.GITLAB_URL || 'https://gitlab.com').replace(/\/+$/, '')

export default defineNuxtConfig({
  compatibilityDate: '2025-06-30',
  devtools: { enabled: true },

  // @nuxt/ui is the UI framework. It bundles & registers @nuxt/icon,
  // @nuxtjs/color-mode and the Tailwind v4 Vite plugin, so we don't list those
  // separately (doing so would double-register them).
  modules: [
    '@nuxt/ui',
    '@nuxtjs/i18n',
    '@pinia/nuxt',
  ],

  // main.css imports both `tailwindcss` and `@nuxt/ui`; then the ported globals
  // (CSS vars + custom classes), the render-pipeline styles (shiki/code chrome)
  // and KaTeX.
  css: [
    '~/assets/css/main.css',
    '~/assets/css/markdown.css',
    'katex/dist/katex.min.css',
  ],

  // color-mode emits BOTH a `.dark` class (for @nuxt/ui's components) and
  // `data-theme="dark"` (for our ported globals/shiki/mermaid CSS). Dark by default.
  colorMode: {
    preference: 'dark',
    fallback: 'dark',
    classSuffix: '',
    dataValue: 'theme',
    storageKey: 'deepwiki-color-mode',
  },

  // Reuses the existing message JSON files (src/messages -> web/i18n/locales).
  // no_prefix keeps URLs clean and language in storage, matching the old behavior.
  i18n: {
    strategy: 'no_prefix',
    defaultLocale: 'en',
    langDir: 'locales',
    detectBrowserLanguage: {
      useCookie: true,
      cookieKey: 'deepwiki-locale',
      redirectOn: 'root',
      fallbackLocale: 'en',
    },
    locales: [
      { code: 'en', file: 'en.json', name: 'English' },
      { code: 'ja', file: 'ja.json', name: 'Japanese (日本語)' },
      { code: 'zh', file: 'zh.json', name: 'Mandarin Chinese (中文)' },
      { code: 'zh-tw', file: 'zh-tw.json', name: 'Traditional Chinese (繁體中文)' },
      { code: 'es', file: 'es.json', name: 'Spanish (Español)' },
      { code: 'kr', file: 'kr.json', name: 'Korean (한국어)' },
      { code: 'vi', file: 'vi.json', name: 'Vietnamese (Tiếng Việt)' },
      { code: 'pt-br', file: 'pt-br.json', name: 'Brazilian Portuguese (Português Brasileiro)' },
      { code: 'fr', file: 'fr.json', name: 'Français (French)' },
      { code: 'ru', file: 'ru.json', name: 'Русский (Russian)' },
    ],
  },

  runtimeConfig: {
    // Server-only: lets server routes/composables reach the backend.
    serverBaseUrl: SERVER_BASE_URL,
    public: {
      // Exposed to the client where it needs the backend origin (e.g. WebSocket URL).
      serverBaseUrl: SERVER_BASE_URL,
      // GitLab web base, used to build source links for cached wiki docs.
      gitlabBase: GITLAB_BASE,
    },
  },

  // BFF proxy layer. Pure pass-throughs to the FastAPI backend (replaces the
  // next.config.ts `rewrites`). Endpoints that had real Next.js route handlers
  // (auth/*, gitlab/*, wiki/projects, models/config, chat/stream) are now Nitro
  // handlers under server/api/ instead.
  routeRules: {
    '/api/lang/config': { proxy: `${SERVER_BASE_URL}/lang/config` },
    '/api/wiki_cache': { proxy: `${SERVER_BASE_URL}/api/wiki_cache` },
    '/api/wiki_cache/**': { proxy: `${SERVER_BASE_URL}/api/wiki_cache/**` },
    '/export/wiki/**': { proxy: `${SERVER_BASE_URL}/export/wiki/**` },
    '/local_repo/structure': { proxy: `${SERVER_BASE_URL}/local_repo/structure` },
  },
})
