<script setup lang="ts">
// Ported from src/app/[owner]/[repo]/page.tsx. The stateful logic lives in
// useWikiData; this file is the render. Full-screen (no app layout) so it also
// embeds cleanly in the home page's iframe.
import type { RepoInfo } from '~/types/wiki'

definePageMeta({ layout: false })

const route = useRoute()
const { t } = useI18n()

function q(key: string): string {
  const v = route.query[key]
  return Array.isArray(v) ? (v[0] || '') : (v ?? '')
}

const owner = String(route.params.owner || '')
const repo = String(route.params.repo || '')
const token = q('token')
const localPath = route.query.local_path ? decodeURIComponent(q('local_path')) : null
const repoUrl = route.query.repo_url ? decodeURIComponent(q('repo_url')) : null
const provider = q('provider')
const model = q('model')
const isCustomModel = q('is_custom_model') === 'true'
const customModel = q('custom_model')
const language = q('language') || 'en'
const isComprehensive = q('comprehensive') !== 'false'
const excludedDirs = q('excluded_dirs')
const excludedFiles = q('excluded_files')
const includedDirs = q('included_dirs')
const includedFiles = q('included_files')

const repoHost = (() => {
  if (!repoUrl) return ''
  try { return new URL(repoUrl).hostname.toLowerCase() } catch { return '' }
})()
const repoType = repoHost.includes('bitbucket')
  ? 'bitbucket'
  : repoHost.includes('gitlab')
    ? 'gitlab'
    : repoHost.includes('github')
      ? 'github'
      : (q('type') || 'github')

const repoInfo: RepoInfo = { owner, repo, type: repoType, token: token || null, localPath, repoUrl }

const {
  isLoading, loadingMessage, error, embeddingError,
  wikiStructure, currentPageId, generatedPages, pagesInProgress,
  effectiveRepoInfo, isExporting, exportError, provider: curProvider, model: curModel,
  generateFileUrl, loadData, exportWiki, selectPage,
} = useWikiData({
  owner, repo, repoInfo, language, isComprehensive, token, provider, model,
  isCustomModel, customModel, excludedDirs, excludedFiles, includedDirs, includedFiles,
})

const currentPage = computed(() =>
  currentPageId.value ? generatedPages.value[currentPageId.value] : undefined,
)
const progressPct = computed(() => {
  const s = wikiStructure.value
  if (!s || !s.pages.length) return 0
  return Math.max(5, (100 * (s.pages.length - pagesInProgress.value.size)) / s.pages.length)
})
const inProgressTitles = computed(() =>
  Array.from(pagesInProgress.value)
    .slice(0, 3)
    .map((id) => wikiStructure.value?.pages.find((p) => p.id === id)?.title)
    .filter(Boolean) as string[],
)
const hasContent = computed(() => Object.keys(generatedPages.value).length > 0)

const repoIcon = computed(() =>
  effectiveRepoInfo.value.type === 'github'
    ? 'i-fa6-brands-github'
    : effectiveRepoInfo.value.type === 'gitlab'
      ? 'i-fa6-brands-gitlab'
      : 'i-fa6-brands-bitbucket',
)

function relatedTitle(id: string) {
  return wikiStructure.value?.pages.find((p) => p.id === id)?.title
}

const contentEl = ref<HTMLElement | null>(null)
watch(currentPageId, () => contentEl.value?.scrollTo({ top: 0, behavior: 'smooth' }))

onMounted(() => {
  const html = document.documentElement
  const prev = html.style.overflow
  html.style.overflow = 'hidden'
  loadData()
  onBeforeUnmount(() => { html.style.overflow = prev })
})
</script>

<template>
  <div class="h-screen paper-texture flex flex-col overflow-hidden">
    <main class="flex-1 w-full overflow-hidden">
      <!-- Loading -->
      <div v-if="isLoading" class="h-full flex items-center justify-center p-8">
        <div class="flex flex-col items-center justify-center p-8 bg-[var(--card-bg)] rounded-lg shadow-custom card-japanese">
          <div class="relative mb-6">
            <div class="absolute -inset-4 bg-[var(--accent-primary)]/10 rounded-full blur-md animate-pulse" />
            <div class="relative flex items-center justify-center">
              <div class="w-3 h-3 bg-[var(--accent-primary)]/70 rounded-full animate-pulse" />
              <div class="w-3 h-3 bg-[var(--accent-primary)]/70 rounded-full animate-pulse delay-75 mx-2" />
              <div class="w-3 h-3 bg-[var(--accent-primary)]/70 rounded-full animate-pulse delay-150" />
            </div>
          </div>
          <p class="text-[var(--foreground)] text-center mb-3 font-serif-jp">
            {{ loadingMessage || t('common.loading') }}
          </p>
          <div v-if="wikiStructure" class="w-full max-w-md mt-3">
            <div class="bg-[var(--background)]/50 rounded-full h-2 mb-3 overflow-hidden border border-[var(--border-color)]">
              <div class="bg-[var(--accent-primary)] h-2 rounded-full transition-all duration-300 ease-in-out" :style="{ width: `${progressPct}%` }" />
            </div>
            <p class="text-xs text-[var(--muted)] text-center">
              {{ wikiStructure.pages.length - pagesInProgress.size }} / {{ wikiStructure.pages.length }}
            </p>
            <ul v-if="inProgressTitles.length" class="mt-4 text-xs text-[var(--foreground)] space-y-1">
              <li v-for="title in inProgressTitles" :key="title" class="truncate border-l-2 border-[var(--accent-primary)]/30 pl-2">{{ title }}</li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="p-6 max-w-2xl mx-auto">
        <div class="bg-[var(--highlight)]/5 border border-[var(--highlight)]/30 rounded-lg p-5 shadow-sm">
          <div class="flex items-center text-[var(--highlight)] mb-3">
            <UIcon name="i-fa6-solid-triangle-exclamation" class="mr-2" />
            <span class="font-bold font-serif-jp">{{ t('repoPage.errorTitle') }}</span>
          </div>
          <p class="text-[var(--foreground)] text-sm mb-3">{{ error }}</p>
          <p class="text-[var(--muted)] text-xs">
            {{ embeddingError ? t('repoPage.embeddingErrorDefault') : t('repoPage.errorMessageDefault') }}
          </p>
          <div class="mt-5">
            <UButton to="/" color="primary" icon="i-fa6-solid-house" :label="t('repoPage.backToHome')" />
          </div>
        </div>
      </div>

      <!-- Wiki view -->
      <div v-else-if="wikiStructure" class="h-full flex flex-col lg:flex-row-reverse bg-[var(--card-bg)] overflow-hidden">
        <!-- Sidebar -->
        <div class="w-full lg:w-[300px] xl:w-[340px] flex-shrink-0 bg-[var(--background)]/50 p-5 border-b lg:border-b-0 lg:border-l border-[var(--border-color)] overflow-y-auto [scrollbar-gutter:stable]">
          <h3 class="text-lg font-bold text-[var(--foreground)] mb-3 font-serif-jp">{{ wikiStructure.title }}</h3>
          <p class="text-[var(--muted)] text-sm mb-5 leading-relaxed">{{ wikiStructure.description }}</p>

          <div class="text-xs text-[var(--muted)] mb-5 flex items-center">
            <template v-if="effectiveRepoInfo.type === 'local'">
              <UIcon name="i-fa6-solid-folder" class="mr-2" />
              <span class="break-all">{{ effectiveRepoInfo.localPath }}</span>
            </template>
            <template v-else>
              <UIcon :name="repoIcon" class="mr-2" />
              <a :href="effectiveRepoInfo.repoUrl ?? ''" target="_blank" rel="noopener noreferrer" class="hover:text-[var(--accent-primary)] transition-colors border-b border-[var(--border-color)] hover:border-[var(--accent-primary)]">
                {{ effectiveRepoInfo.owner }}/{{ effectiveRepoInfo.repo }}
              </a>
            </template>
          </div>

          <div class="mb-4 flex items-center gap-2 text-xs text-[var(--muted)]">
            <span>Wiki Type:</span>
            <UBadge :color="isComprehensive ? 'primary' : 'neutral'" variant="soft" size="sm" :label="isComprehensive ? t('form.comprehensive') : t('form.concise')" />
          </div>

          <div class="mb-5 flex gap-2">
            <UButton :to="{ path: `/${owner}/${repo}/slides`, query: route.query }" color="neutral" variant="outline" size="xs" icon="i-fa6-solid-display" label="Slides" />
            <UButton :to="{ path: `/${owner}/${repo}/workshop`, query: route.query }" color="neutral" variant="outline" size="xs" icon="i-fa6-solid-graduation-cap" label="Workshop" />
          </div>

          <div v-if="hasContent" class="mb-5">
            <h4 class="text-sm font-semibold text-[var(--foreground)] mb-3 font-serif-jp">{{ t('repoPage.exportWiki') }}</h4>
            <div class="flex flex-col gap-2">
              <UButton color="primary" variant="solid" size="sm" icon="i-fa6-solid-download" :loading="isExporting" :label="t('repoPage.exportAsMarkdown')" @click="exportWiki('markdown')" />
              <UButton color="neutral" variant="outline" size="sm" icon="i-fa6-solid-file-export" :disabled="isExporting" :label="t('repoPage.exportAsJson')" @click="exportWiki('json')" />
            </div>
            <p v-if="exportError" class="mt-2 text-xs text-[var(--highlight)]">{{ exportError }}</p>
          </div>

          <h4 class="text-md font-semibold text-[var(--foreground)] mb-3 font-serif-jp">{{ t('repoPage.pages') }}</h4>
          <WikiTreeView :wiki-structure="wikiStructure" :current-page-id="currentPageId" @page-select="selectPage" />
        </div>

        <!-- Content -->
        <div id="wiki-content" ref="contentEl" class="w-full flex-grow p-6 lg:p-8 overflow-y-auto [scrollbar-gutter:stable]">
          <div v-if="currentPage" class="max-w-full mx-auto pb-28">
            <h3 class="text-xl font-bold text-[var(--foreground)] mb-4 break-words font-serif-jp">{{ currentPage.title }}</h3>
            <Suspense :key="currentPageId">
              <Markdown :content="currentPage.content" :resolve-file-href="generateFileUrl" />
              <template #fallback>
                <div class="p-8 text-center text-[var(--muted)] text-sm">{{ t('common.loading') }}</div>
              </template>
            </Suspense>

            <div v-if="currentPage.relatedPages.length" class="mt-8 pt-4 border-t border-[var(--border-color)]">
              <h4 class="text-sm font-semibold text-[var(--muted)] mb-3">{{ t('repoPage.relatedPages') }}</h4>
              <div class="flex flex-wrap gap-2">
                <template v-for="rid in currentPage.relatedPages" :key="rid">
                  <UButton v-if="relatedTitle(rid)" color="primary" variant="soft" size="xs" :label="relatedTitle(rid)" @click="selectPage(rid)" />
                </template>
              </div>
            </div>
          </div>
          <div v-else class="flex flex-col items-center justify-center p-8 text-[var(--muted)] h-full">
            <UIcon name="i-fa6-solid-book-open" class="text-4xl mb-4" />
            <p class="font-serif-jp">{{ t('repoPage.selectPagePrompt') }}</p>
          </div>
        </div>
      </div>
    </main>

    <!-- Docked Ask panel -->
    <div v-if="!isLoading && wikiStructure" class="fixed bottom-0 left-0 right-0 lg:right-[300px] xl:right-[340px] z-40 px-3 pb-3 pointer-events-none">
      <div class="mx-auto w-full max-w-2xl pointer-events-auto bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl shadow-2xl overflow-hidden card-japanese">
        <AskPanel
          :repo-info="effectiveRepoInfo"
          :provider="curProvider"
          :model="curModel"
          :is-custom-model="isCustomModel"
          :custom-model="customModel"
          :language="language"
        />
      </div>
    </div>
  </div>
</template>
