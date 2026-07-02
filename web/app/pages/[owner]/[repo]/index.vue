<script setup lang="ts">
// Ported from src/app/[owner]/[repo]/page.tsx. The stateful logic lives in
// useWikiData; this file is the render. Full-screen (no app layout) so it also
// embeds cleanly in the home page's iframe.
import type { RepoInfo } from '~/types/wiki'

// Renders inside the `home` dashboard shell (left sidebar persists; wiki tree +
// content fill the right panel). Sibling routes (/, /wikis) share this layout, so
// switching keeps the dashboard mounted.
definePageMeta({ layout: 'home' })

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
const language = 'zh' // wikis are Chinese-only; kept as cache-identity plumbing
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
  pageBusy, pageActionError,
  generateFileUrl, loadData, exportWiki, selectPage,
  savePageEdit, regeneratePage, revertPage, fetchPageHistory,
} = useWikiData({
  owner, repo, repoInfo, language, isComprehensive, token, provider, model,
  isCustomModel, customModel, excludedDirs, excludedFiles, includedDirs, includedFiles,
})

const currentPage = computed(() =>
  currentPageId.value ? generatedPages.value[currentPageId.value] : undefined,
)

// --- per-page edit / regenerate / revert ---
const editing = ref(false)
const editMode = ref<'rich' | 'source'>('rich')
const editContent = ref('')
const regenOpen = ref(false)
const instruction = ref('')
const historyOpen = ref(false)
const busy = computed(() => !!currentPage.value && pageBusy.value === currentPage.value.id)

function fmtTime(ms?: number) {
  if (!ms) return ''
  try { return new Date(ms).toLocaleString() } catch { return '' }
}
function startEdit() {
  if (!currentPage.value) return
  editContent.value = currentPage.value.content
  regenOpen.value = false
  editMode.value = 'rich'
  editing.value = true
}
function setEditMode(m: 'rich' | 'source') { editMode.value = m }
async function saveEdit() {
  if (!currentPage.value) return
  if (await savePageEdit(currentPage.value.id, editContent.value)) editing.value = false
}
async function doRegen() {
  if (!currentPage.value) return
  if (await regeneratePage(currentPage.value.id, instruction.value.trim())) {
    regenOpen.value = false
    instruction.value = ''
  }
}
function doRevert() {
  if (currentPage.value) void revertPage(currentPage.value.id)
}
function toggleRegen() { regenOpen.value = !regenOpen.value }
function closeRegen() { regenOpen.value = false }
function cancelEdit() { editing.value = false }
function openHistory() { historyOpen.value = true }
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

const breadcrumbItems = computed(() => [
  { label: 'Wiki 文档', icon: 'i-lucide-book-marked', to: '/wikis' },
  { label: `${owner}/${repo}` },
])

const contentEl = ref<HTMLElement | null>(null)
watch(currentPageId, () => {
  editing.value = false
  regenOpen.value = false
  instruction.value = ''
  contentEl.value?.scrollTo({ top: 0, behavior: 'smooth' })
})

// The `home` layout/dashboard owns full-height/no-scroll now, so no html overflow hack.
onMounted(loadData)
</script>

<template>
  <div class="h-full bg-default flex flex-col overflow-hidden relative">
    <main class="flex-1 w-full overflow-hidden">
      <!-- Loading -->
      <div v-if="isLoading" class="h-full flex items-center justify-center p-8">
        <div class="flex flex-col items-center justify-center p-8 rounded-lg shadow-lg">
          <div class="relative mb-6">
            <div class="absolute -inset-4 bg-primary/10 rounded-full blur-md animate-pulse" />
            <div class="relative flex items-center justify-center">
              <div class="w-3 h-3 bg-primary/70 rounded-full animate-pulse" />
              <div class="w-3 h-3 bg-primary/70 rounded-full animate-pulse delay-75 mx-2" />
              <div class="w-3 h-3 bg-primary/70 rounded-full animate-pulse delay-150" />
            </div>
          </div>
          <p class="text-default text-center mb-3">
            {{ loadingMessage || t('common.loading') }}
          </p>
          <div v-if="wikiStructure" class="w-full max-w-md mt-3">
            <div class="bg-default/50 rounded-full h-2 mb-3 overflow-hidden border border-default">
              <div class="bg-primary h-2 rounded-full transition-all duration-300 ease-in-out" :style="{ width: `${progressPct}%` }" />
            </div>
            <p class="text-xs text-muted text-center">
              {{ wikiStructure.pages.length - pagesInProgress.size }} / {{ wikiStructure.pages.length }}
            </p>
            <ul v-if="inProgressTitles.length" class="mt-4 text-xs text-default space-y-1">
              <li v-for="title in inProgressTitles" :key="title" class="truncate border-l-2 border-primary/30 pl-2">{{ title }}</li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="p-6 max-w-2xl mx-auto">
        <div class="bg-error/5 border border-error/30 rounded-lg p-5 shadow-sm">
          <div class="flex items-center text-error mb-3">
            <UIcon name="i-fa6-solid-triangle-exclamation" class="mr-2" />
            <span class="font-bold">{{ t('repoPage.errorTitle') }}</span>
          </div>
          <p class="text-default text-sm mb-3">{{ error }}</p>
          <p class="text-muted text-xs">
            {{ embeddingError ? t('repoPage.embeddingErrorDefault') : t('repoPage.errorMessageDefault') }}
          </p>
          <div class="mt-5">
            <UButton to="/" color="primary" icon="i-fa6-solid-house" :label="t('repoPage.backToHome')" />
          </div>
        </div>
      </div>

      <!-- Wiki view -->
      <div v-else-if="wikiStructure" class="h-full flex flex-col overflow-hidden">
        <!-- Top toolbar: breadcrumb + repo + wiki type + export -->
        <div class="flex items-center gap-x-3 gap-y-1.5 px-4 sm:px-5 py-2 border-b border-default shrink-0 flex-wrap">
          <UBreadcrumb :items="breadcrumbItems" />

          <div class="text-xs text-muted flex items-center gap-1.5 min-w-0">
            <template v-if="effectiveRepoInfo.type === 'local'">
              <UIcon name="i-fa6-solid-folder" class="shrink-0" />
              <span class="truncate">{{ effectiveRepoInfo.localPath }}</span>
            </template>
            <template v-else>
              <UIcon :name="repoIcon" class="shrink-0" />
              <a :href="effectiveRepoInfo.repoUrl ?? ''" target="_blank" rel="noopener noreferrer" class="truncate hover:text-primary transition-colors">
                {{ effectiveRepoInfo.owner }}/{{ effectiveRepoInfo.repo }}
              </a>
            </template>
          </div>

          <UBadge :color="isComprehensive ? 'primary' : 'neutral'" variant="soft" size="sm" :label="isComprehensive ? t('form.comprehensive') : t('form.concise')" />

          <div v-if="hasContent" class="ml-auto flex items-center gap-2">
            <UButton color="neutral" variant="outline" size="xs" icon="i-fa6-solid-download" :loading="isExporting" :label="t('repoPage.exportAsMarkdown')" @click="exportWiki('markdown')" />
            <UButton color="neutral" variant="outline" size="xs" icon="i-fa6-solid-file-export" :disabled="isExporting" :label="t('repoPage.exportAsJson')" @click="exportWiki('json')" />
          </div>
          <p v-if="exportError" class="w-full text-xs text-error">{{ exportError }}</p>
        </div>
        <div class="flex-1 min-h-0 flex flex-col lg:flex-row-reverse overflow-hidden">
          <!-- Wiki tree — Nuxt UI sidebar docked on the right -->
          <UDashboardSidebar
            id="wiki-tree"
            side="right"
            resizable
            :default-size="22"
            :min-size="16"
            :max-size="34"
            :ui="{ root: 'dash-sidebar min-h-0 h-full', body: 'p-5 pt-2 overflow-y-auto', header: 'p-5 pb-2' }"
          >
            <template #header>
              <h3 class="text-lg font-bold text-default truncate">{{ wikiStructure.title }}</h3>
            </template>
          <p class="text-muted text-sm mb-2 leading-relaxed">{{ wikiStructure.description }}</p>

          <!-- <h4 class="text-md font-semibold text-default mb-3">{{ t('repoPage.pages') }}</h4> -->
          <WikiTreeView :wiki-structure="wikiStructure" :current-page-id="currentPageId" @page-select="selectPage" />
          </UDashboardSidebar>

        <!-- Content -->
        <div id="wiki-content" ref="contentEl" class="w-full flex-grow p-6 lg:p-8 overflow-y-auto [scrollbar-gutter:stable]">
          <div v-if="currentPage" class="max-w-full mx-auto pb-28">
            <!-- Title + per-page actions -->
            <div class="flex items-start justify-between gap-3 mb-4 flex-wrap">
              <div class="min-w-0">
                <h3 class="text-xl font-bold text-default break-words">{{ currentPage.title }}</h3>
                <div class="flex items-center gap-2 mt-1 text-xs text-muted">
                  <UBadge v-if="currentPage.edited" color="warning" variant="soft" size="xs" label="已手动编辑" />
                  <span v-if="currentPage.updated_at">更新于 {{ fmtTime(currentPage.updated_at) }}</span>
                </div>
              </div>
              <div v-if="!editing" class="flex items-center gap-1.5 shrink-0">
                <UButton color="neutral" variant="outline" size="xs" icon="i-lucide-pencil" label="编辑" :disabled="busy" @click="startEdit" />
                <UButton color="primary" variant="outline" size="xs" icon="i-lucide-rotate-cw" label="重新生成" :disabled="busy" @click="toggleRegen" />
                <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-history" label="历史" :disabled="busy" @click="openHistory" />
                <UButton v-if="currentPage.prev_content" color="neutral" variant="ghost" size="xs" icon="i-lucide-undo-2" label="回滚" :loading="busy" :disabled="busy" @click="doRevert" />
              </div>
            </div>

            <!-- Regenerate panel (optional instruction) -->
            <div v-if="regenOpen && !editing" class="mb-5 border border-default rounded-lg p-3 bg-muted/30">
              <p class="text-xs text-muted mb-2">可选：告诉 AI 哪里要改（留空则按当前模板整页重生）</p>
              <UTextarea v-model="instruction" :rows="2" class="w-full" placeholder="例如：业务流程图画反了，应为 登录→鉴权→回调；补充异常用例" />
              <div class="flex items-center gap-2 mt-2">
                <UButton color="primary" size="xs" icon="i-lucide-sparkles" label="开始重新生成" :loading="busy" @click="doRegen" />
                <UButton color="neutral" variant="ghost" size="xs" label="取消" :disabled="busy" @click="closeRegen" />
                <span v-if="busy" class="text-xs text-muted">生成中，约 15-40 秒…</span>
              </div>
            </div>

            <p v-if="pageActionError" class="mb-3 text-xs text-error">{{ pageActionError }}</p>

            <!-- Edit mode: editor (rich / source) + live preview -->
            <div v-if="editing">
              <div class="flex items-center gap-2 mb-2 flex-wrap">
                <div class="flex items-center rounded-md border border-default overflow-hidden">
                  <UButton :color="editMode === 'rich' ? 'primary' : 'neutral'" :variant="editMode === 'rich' ? 'soft' : 'ghost'" size="xs" icon="i-lucide-type" label="富文本" @click="setEditMode('rich')" />
                  <UButton :color="editMode === 'source' ? 'primary' : 'neutral'" :variant="editMode === 'source' ? 'soft' : 'ghost'" size="xs" icon="i-lucide-code" label="源码" @click="setEditMode('source')" />
                </div>
                <UButton color="primary" size="xs" icon="i-lucide-save" label="保存" :loading="busy" @click="saveEdit" />
                <UButton color="neutral" variant="ghost" size="xs" label="取消" :disabled="busy" @click="cancelEdit" />
                <span class="text-xs text-muted">含 &lt;details&gt;/引用/mermaid 的页面，建议用「源码」精修</span>
              </div>
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div class="flex flex-col min-w-0 h-[70vh]">
                  <WikiMarkdownEditor v-if="editMode === 'rich'" v-model="editContent" class="h-full" />
                  <UTextarea v-else v-model="editContent" :rows="26" class="w-full h-full" :ui="{ base: 'font-mono text-sm h-full' }" />
                </div>
                <div class="min-w-0">
                  <label class="text-xs text-muted mb-1 block">预览（与实际页面一致）</label>
                  <div class="border border-default rounded-lg p-4 overflow-auto h-[70vh]">
                    <Markdown :content="editContent" :resolve-file-href="generateFileUrl" />
                  </div>
                </div>
              </div>
            </div>

            <!-- View mode -->
            <template v-else>
              <Suspense :key="currentPageId">
                <Markdown :content="currentPage.content" :resolve-file-href="generateFileUrl" />
                <template #fallback>
                  <div class="p-8 text-center text-muted text-sm">{{ t('common.loading') }}</div>
                </template>
              </Suspense>

              <div v-if="currentPage.relatedPages.length" class="mt-8 pt-4 border-t border-default">
                <h4 class="text-sm font-semibold text-muted mb-3">{{ t('repoPage.relatedPages') }}</h4>
                <div class="flex flex-wrap gap-2">
                  <template v-for="rid in currentPage.relatedPages" :key="rid">
                    <UButton v-if="relatedTitle(rid)" color="primary" variant="soft" size="xs" :label="relatedTitle(rid)" @click="selectPage(rid)" />
                  </template>
                </div>
              </div>
            </template>
          </div>
          <div v-else class="flex flex-col items-center justify-center p-8 text-muted h-full">
            <UIcon name="i-fa6-solid-book-open" class="text-4xl mb-4" />
            <p class="">{{ t('repoPage.selectPagePrompt') }}</p>
          </div>
        </div>
        </div>
      </div>
    </main>

    <!-- Per-page change timeline (history + diff + revert) -->
    <WikiHistoryTimeline
      v-if="currentPage"
      v-model="historyOpen"
      :page-id="currentPage.id"
      :page-title="currentPage.title"
      :fetch-history="fetchPageHistory"
      :revert="revertPage"
    />

    <!-- Docked Ask panel (anchored to this panel, not the viewport) -->
    <div v-if="!isLoading && wikiStructure" class="absolute bottom-0 left-0 right-0 lg:right-[24%] z-40 px-3 pb-3 pointer-events-none">
      <div class="mx-auto w-full max-w-2xl pointer-events-auto bg-elevated border border-default rounded-xl shadow-2xl overflow-hidden bg-elevated">
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
