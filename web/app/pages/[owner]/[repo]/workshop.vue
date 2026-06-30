<script setup lang="ts">
// Ported from src/app/[owner]/[repo]/workshop/page.tsx.
import type { RepoInfo } from '~/types/wiki'

definePageMeta({ layout: false })

const route = useRoute()
const baseUrl = (useRuntimeConfig().public.serverBaseUrl as string) || 'http://localhost:8001'

function q(key: string): string {
  const v = route.query[key]
  return Array.isArray(v) ? (v[0] || '') : (v ?? '')
}

const owner = String(route.params.owner || '')
const repo = String(route.params.repo || '')
const repoType = q('type') || 'github'
const language = q('language') || 'en'
const provider = q('provider')
const model = q('model')
const isCustomModel = q('is_custom_model') === 'true'
const customModel = q('custom_model')

const repoInfo: RepoInfo = {
  owner,
  repo,
  type: repoType,
  token: q('token') || null,
  localPath: route.query.local_path ? decodeURIComponent(q('local_path')) : null,
  repoUrl: route.query.repo_url ? decodeURIComponent(q('repo_url')) : null,
}

const isLoading = ref(false)
const loadingMessage = ref<string | undefined>('Generating workshop content...')
const error = ref<string | null>(null)
const workshopContent = ref('')
const isExporting = ref(false)
const exportError = ref<string | null>(null)

const backTo = computed(() => ({ path: `/${owner}/${repo}`, query: route.query }))

// Add a TOC + exercise progress indicators (ported post-processing).
function postProcess(content: string): string {
  let out = content.replace(/^```markdown\s*/i, '').replace(/```\s*$/i, '')

  if (!out.includes('## Table of Contents') && !out.includes('## Contents')) {
    const headings = out.match(/^## (.*)$/gm) || []
    if (headings.length) {
      let toc = '## Table of Contents\n\n'
      for (const h of headings) {
        const text = h.replace('## ', '')
        const link = text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-')
        toc += `- [${text}](#${link})\n`
      }
      toc += '\n'
      const introPos = out.indexOf('# ') + 1
      const nextHeading = out.indexOf('## ', introPos)
      if (nextHeading > introPos) out = out.slice(0, nextHeading) + toc + out.slice(nextHeading)
    }
  }

  const exercises = out.match(/^## Exercise \d+:/gm) || []
  for (let i = 0; i < exercises.length; i++) {
    let estimate = 10
    if (i === 0) estimate = 5
    else if (i === exercises.length - 1) estimate = 15
    else if (i > Math.floor(exercises.length / 2)) estimate = 12
    const indicator = `<div style="text-align: right; font-size: 0.85em; color: #666;">\nExercise ${i + 1} of ${exercises.length} | Estimated time: ${estimate} minutes\n</div>\n\n`
    const pos = out.indexOf(exercises[i])
    if (pos !== -1) {
      const eol = out.indexOf('\n', pos)
      if (eol !== -1) out = out.slice(0, eol + 1) + indicator + out.slice(eol + 1)
    }
  }

  const finalProject = out.match(/^## Final Project/m)
  if (finalProject) {
    const pos = out.indexOf(finalProject[0])
    const eol = out.indexOf('\n', pos)
    if (eol !== -1) {
      const note = `<div style="text-align: right; font-size: 0.85em; color: #666;">\nEstimated time: 20-30 minutes | Combines concepts from all exercises\n</div>\n\n`
      out = out.slice(0, eol + 1) + note + out.slice(eol + 1)
    }
  }
  return out
}

async function generate() {
  if (isLoading.value) return
  isLoading.value = true
  error.value = null
  workshopContent.value = ''
  loadingMessage.value = 'Generating workshop content...'
  try {
    const wikiData = await fetchCachedWiki(owner, repo, repoType, language)
    const wikiContent = buildWikiContext(wikiData)
    const body: ChatStreamRequest = {
      repo_url: getRepoUrl(repoInfo),
      type: repoInfo.type,
      messages: [{ role: 'user', content: buildWorkshopPrompt({ owner, repo, wikiContent, language }) }],
    }
    addTokensToRequestBody(body, { token: repoInfo.token || '', provider, model, isCustomModel, customModel, language })
    const content = await streamChat(baseUrl, body, (full) => { workshopContent.value = full })
    workshopContent.value = postProcess(content)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'An unknown error occurred'
  } finally {
    isLoading.value = false
    loadingMessage.value = undefined
  }
}

function exportWorkshop() {
  if (!workshopContent.value) {
    exportError.value = 'No workshop content to export'
    return
  }
  try {
    isExporting.value = true
    exportError.value = null
    const blob = new Blob([workshopContent.value], { type: 'text/markdown' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${repo}_workshop.md`
    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)
  } catch (err) {
    exportError.value = err instanceof Error ? err.message : 'An unknown error occurred'
  } finally {
    isExporting.value = false
  }
}

onMounted(generate)
</script>

<template>
  <div class="min-h-screen flex flex-col bg-default">
    <header class="sticky top-0 z-10 bg-elevated border-b border-default shadow-sm">
      <div class="container mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-4">
          <NuxtLink :to="backTo" class="flex items-center text-default hover:text-primary transition-colors">
            <UIcon name="i-fa6-solid-arrow-left" class="mr-2" />
            <span>返回 Wiki</span>
          </NuxtLink>
          <h1 class="text-xl font-bold text-primary">Workshop: {{ repo }}</h1>
        </div>
        <div class="flex items-center gap-2">
          <UButton color="primary" variant="soft" icon="i-fa6-solid-arrows-rotate" :loading="isLoading" square aria-label="Regenerate" @click="generate" />
          <UButton color="primary" variant="soft" icon="i-fa6-solid-download" :disabled="!workshopContent || isExporting" square aria-label="Export" @click="exportWorkshop" />
        </div>
      </div>
    </header>

    <main class="flex-1 container mx-auto px-4 py-6">
      <div v-if="isLoading && !workshopContent" class="flex flex-col items-center justify-center p-8">
        <div class="w-12 h-12 border-4 border-primary/30 border-t-primary rounded-full animate-spin mb-4" />
        <p class="text-default">{{ loadingMessage }}</p>
      </div>
      <UAlert v-else-if="error" color="error" variant="soft" title="Error" :description="error" />
      <div v-else class="bg-elevated border border-default rounded-lg shadow-sm p-6">
        <UAlert v-if="exportError" color="error" variant="soft" class="mb-4" :description="exportError" />
        <Suspense>
          <Markdown :content="workshopContent" />
          <template #fallback>
            <div class="p-8 text-center text-muted text-sm">…</div>
          </template>
        </Suspense>
      </div>
    </main>
  </div>
</template>
