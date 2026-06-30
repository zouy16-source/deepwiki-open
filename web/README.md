# DeepWiki Web (Nuxt 4)

Nuxt 4 rewrite of the DeepWiki frontend, replacing the Next.js 15 / React 19 app
in `../src`. The Python FastAPI backend (`../api`, on `:8001`) is **unchanged** —
this app is a thin client + BFF proxy over it.

## Run

```bash
cd web
npm install
# Provide backend env for the BFF (see .env.example). Either copy it:
cp .env.example .env        # then edit GITLAB_TOKEN etc.
# ...or reuse the repo-root .env:
set -a; . ../.env; set +a
npm run dev                 # http://localhost:3001
```

> Node 20.19+ works. Some transitive build deps (cssnano/postcss-svgo) print
> `EBADENGINE` warnings asking for Node 22+; they are optional and don't affect
> dev/build. Use Node 22 LTS to silence them.

## Stack & why

| Concern | Choice |
|---|---|
| Framework | Nuxt 4 (Vue 3, Nitro, Vite 7) |
| UI library | `@nuxt/ui` v4 (Reka UI + Tailwind v4). It bundles & registers `@nuxt/icon`, `@nuxtjs/color-mode` and the Tailwind Vite plugin, so those aren't listed in `modules` separately. `primary` ≈ VSCode blue (`app.config.ts`); surfaces still use the `--*` CSS vars |
| Styling | Tailwind v4 via `@tailwindcss/vite`; `app/assets/css/main.css` is ported verbatim from the old `globals.css` (CSS variables + `@custom-variant dark`) |
| Theming | `@nuxtjs/color-mode` → writes `data-theme="dark"` on `<html>`, dark default (replaces `next-themes`) |
| i18n | `@nuxtjs/i18n` (vue-i18n), `no_prefix`; locale JSON in `i18n/locales/` reused 1:1 from `src/messages` (replaces `next-intl` + custom `LanguageContext`) |
| Icons | `@nuxt/icon` + `@iconify-json/fa6-*` (replaces `react-icons/fa`) |
| State | Pinia (`@pinia/nuxt`) for cross-page state (selected repo, etc.) |
| BFF | Nitro `routeRules` proxy + `server/api/*` (replaces `next.config` rewrites + `src/app/api/*`) |

## Next.js → Nuxt mapping

| Next.js | Nuxt 4 |
|---|---|
| `src/app/.../page.tsx` | `app/pages/*.vue` |
| `src/app/[owner]/[repo]/page.tsx` | `app/pages/[owner]/[repo].vue` |
| `layout.tsx` + Providers | `app/app.vue` + `app/layouts/default.vue` |
| `src/app/api/.../route.ts` | `server/api/.../*.ts` |
| `next.config` rewrites | `routeRules: { proxy }` |
| React Context | composables / Pinia |
| React hooks | `ref` / `computed` / `watch` |
| `useParams` / `useSearchParams` | `useRoute()` |
| `react-markdown` stack | `markdown-it` + `shiki` + `markdown-it-katex` + Mermaid component |

## Migration phases

- [x] **Phase 0 — Scaffold + infra** (this commit)
  - [x] Nuxt 4 project, Tailwind v4, CSS variables ported verbatim
  - [x] i18n wired to existing 10-language JSON
  - [x] color-mode → `data-theme`, dark default
  - [x] `@nuxt/icon` with FontAwesome collections
  - [x] BFF proxy `routeRules` for backend pass-throughs
  - [x] Self-check page (`/`) verifying all of the above
- [x] **Phase 1 — BFF routes** (verified against the live backend)
  - [x] `server/api/auth/{status.get,validate.post}`, `models/config.get`,
        `wiki/projects.{get,delete}`, `gitlab/{projects,file_tree,default_branch}.get`,
        `chat/stream.post` (SSE pass-through)
  - [x] `server/utils/backend.ts` reads the SAME env names as before
        (`SERVER_BASE_URL`, `PYTHON_BACKEND_HOST`, `GITLAB_URL`, `GITLAB_TOKEN`)
  - [x] `default_branch` calls GitLab API v4 directly (self-hosted supported)
  - Pure pass-throughs (`wiki_cache`, `export/wiki`, `local_repo/structure`,
    `lang/config`) stay as `routeRules` proxies in `nuxt.config.ts`
- [x] **Phase 2 — Render pipeline** (verified at `/markdown-demo`)
  - [x] `Markdown.vue` + `composables/useMarkdownRenderer.ts`: markdown-it with renderer
        rules reproducing the React per-element classes, ReAct h2 styling, GFM tables,
        raw HTML, KaTeX (`@vscode/markdown-it-katex`), shiki dual-theme highlight with
        code-block header + copy button, and the citation-link resolution
        (`isBareFilePath` / `citationHref` ported 1:1)
  - [x] `Mermaid.vue`: async `mermaid.render`, dark-mode `data-theme` injection,
        click-to-fullscreen modal (wheel/buttons zoom, Esc, click-outside),
        optional svg-pan-zoom; client-only
  - [x] shiki uses the JS RegExp engine (no WASM) for clean SSR + client
  - SSR renders all markdown features; mermaid renders client-side
- [x] **Phase 3 — Lists & home** (consumes the BFF; @nuxt/ui adopted)
  - [x] `@nuxt/ui` v4 integrated; dark mode unified (`.dark` + `[data-theme]`), `<UApp>` in `app.vue`
  - [x] `GitlabProjectList.vue` + `WikiDocList.vue` (search/table/badge/pagination;
        delete uses `UModal` + `useToast` instead of `confirm()`/`alert()`)
  - [x] `pages/index.vue` home dashboard (sidebar tabs + list content + iframe wiki view)
  - [x] self-check moved to `/dev`; render demo at `/markdown-demo`
- [x] **Phase 4 — Wiki main page** (2222-line `[owner]/[repo]/page.tsx` decomposed)
  - [x] `composables/useWikiData.ts` — owns all state; cache-load (GET `/api/wiki_cache`),
        generate path (fetch repo tree per provider → WS structure XML → sequential
        page generation → save cache), export, section-grouping fallback
  - [x] `utils/chatStream.ts` — single WS+HTTP-fallback streamer (was duplicated ×3)
  - [x] `utils/wikiPrompts.ts` (structure + page prompts), `utils/repo.ts` (helpers),
        `types/wiki.ts`
  - [x] `components/WikiTreeView.vue` + recursive `WikiTreeSection.vue`,
        `components/AskPanel.vue` (simplified input-only Ask over the chat stream)
  - [x] `pages/[owner]/[repo].vue` — render only (`layout: false`, full-screen for the
        home iframe); @nuxt/ui for chrome (buttons/badges/icons/textarea)
  - **Cache-view path verified** end-to-end (renders a real cached wiki: 11 pages /
    6 sections / mermaid). Generate path ported faithfully but needs a key-configured
    backend to exercise. The dead Refresh button + ModelSelectionModal were dropped
    (commented out in the source).
- [x] **Phase 5 — slides / workshop**
  - [x] `utils/wikiContext.ts` — shared cached-wiki fetch + size-capped context
        assembly (was duplicated in both pages)
  - [x] `utils/wikiPrompts.ts` — added `buildWorkshopPrompt`, `buildSlidePlanPrompt`,
        `buildSlidePrompt`
  - [x] `pages/[owner]/[repo]/workshop.vue` — generate → post-process (TOC / exercise
        progress / final-project note) → `<Markdown>` → export `.md`
  - [x] `pages/[owner]/[repo]/slides.vue` — plan → per-slide HTML → viewer
        (prev/next, fullscreen, keyboard) → export standalone `.html`
  - [x] wiki page moved to `[owner]/[repo]/index.vue`; sidebar links to Slides/Workshop
  - Generation needs a key-configured backend; routing/cache/render/nav/export verified

**Migration complete** — all 7 routes (`/`, `/dev`, `/markdown-demo`, `/[owner]/[repo]`,
`…/slides`, `…/workshop`) render SSR-clean against the live backend. The cache-view
and list/home paths are verified end-to-end; the LLM-generation paths are ported and
need backend API keys to exercise. The old Next.js app under `../src` can be retired
once the generation paths are confirmed in a key-configured environment.

## Known porting risks

- **Markdown paradigm shift**: react-markdown overrides components; markdown-it uses
  render rules/plugins. The custom citation logic (`citationHref`, `isBareFilePath`,
  `nodeText` in `src/components/Markdown.tsx`) must be reimplemented as a markdown-it
  rule or a post-render DOM pass.
- **Mermaid + svg-pan-zoom** (538 lines): core is framework-agnostic SVG strings; only
  the React lifecycle → Vue lifecycle changes.
- **WebSocket streaming** (`src/utils/websocketClient.ts`): plain Web API, moves into a
  composable; client needs `useRuntimeConfig().public.serverBaseUrl` to build the `ws://` URL.

## Layout

```
web/
  nuxt.config.ts          # modules, i18n, color-mode, Tailwind, proxy routeRules
  i18n/locales/*.json     # reused from src/messages
  app/
    app.vue               # head/fonts + <NuxtLayout><NuxtPage>
    assets/css/           # main.css (ported globals.css) + markdown.css (shiki/katex)
    layouts/default.vue    # header (logo + locale switcher + theme toggle)
    components/            # ThemeToggle, LocaleSwitcher, Markdown, Mermaid
    composables/           # useMarkdownRenderer (markdown-it + shiki + katex)
    pages/                 # index.vue (self-check), markdown-demo.vue, then ported routes
  server/                 # Nitro API handlers (Phase 1+)
```
