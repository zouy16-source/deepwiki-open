<script setup lang="ts">
// Ported from src/app/[owner]/[repo]/slides/page.tsx. Generates a plan, then one
// HTML slide per title, and shows them in a viewer with nav/fullscreen/export.
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

interface Slide { id: string; title: string; content: string; html: string }

const isLoading = ref(false)
const loadingMessage = ref<string | undefined>('Generating slides...')
const error = ref<string | null>(null)
const slides = ref<Slide[]>([])
const currentSlideIndex = ref(0)
const isExporting = ref(false)
const exportError = ref<string | null>(null)
const isFullscreen = ref(false)

const backTo = computed(() => ({ path: `/${owner}/${repo}`, query: route.query }))
const currentSlide = computed(() => slides.value[currentSlideIndex.value])

function parseSlidePlan(plan: string): string[] {
  const lines: string[] = []
  let m: RegExpExecArray | null
  const p1 = /\d+\.\s+(.*?)(?=\n\d+\.|\n*$)/g
  while ((m = p1.exec(plan)) !== null) lines.push(m[1])
  if (!lines.length) {
    const p2 = /\d+\)\s+(.*?)(?=\n\d+\)|\n*$)/g
    while ((m = p2.exec(plan)) !== null) lines.push(m[1])
  }
  if (!lines.length) {
    const p3 = /Slide\s+\d+\s*:?\s*(.*?)(?=\nSlide|\n*$)/gi
    while ((m = p3.exec(plan)) !== null) lines.push(m[1])
  }
  if (!lines.length) {
    const p4 = /^([^:\n]+)(?::\s*(.*?))?$/gm
    while ((m = p4.exec(plan)) !== null) {
      const t = m[1]
      if (t.length > 3 && !t.toLowerCase().includes('please') && !t.toLowerCase().includes('here')) lines.push(t)
    }
  }
  if (!lines.length) {
    lines.push(
      `Title Slide: Introduction to ${repo}`,
      `Overview: Key features and purpose of ${repo}`,
      `Architecture: System components and structure`,
      `Features: Main capabilities and functionalities`,
      `Implementation: How it works and technical details`,
      `Use Cases: How to use ${repo} effectively`,
      `Conclusion: Summary and next steps`,
    )
  }
  return lines
}

function cleanSlideHtml(raw: string, title: string): string {
  const html = raw
    .replace(/^```html\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/```\s*$/i, '')
    .trim()
  if (html) return html
  // Fallback when the model returns nothing usable.
  return `<div class="slide" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);color:#e6edf3;">
    <h1 style="font-size:3rem;background:linear-gradient(135deg,#58a6ff 0%,#8957e5 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">${title}</h1>
  </div>`
}

async function generate() {
  if (isLoading.value) return
  isLoading.value = true
  error.value = null
  slides.value = []
  currentSlideIndex.value = 0
  loadingMessage.value = 'Generating slides...'
  try {
    const wikiData = await fetchCachedWiki(owner, repo, repoType, language)
    const wikiContent = buildWikiContext(wikiData)

    const planBody: ChatStreamRequest = {
      repo_url: getRepoUrl(repoInfo),
      type: repoInfo.type,
      messages: [{ role: 'user', content: buildSlidePlanPrompt({ owner, repo, wikiContent }) }],
    }
    addTokensToRequestBody(planBody, { token: repoInfo.token || '', provider, model, isCustomModel, customModel, language })
    const planContent = await streamChat(baseUrl, planBody)
    const titles = parseSlidePlan(planContent)

    const built: Slide[] = []
    for (let i = 0; i < titles.length; i++) {
      const line = titles[i]
      const slideTitle = line.split(':')[0].trim()
      const slideDescription = line.includes(':') ? line.split(':')[1].trim() : ''
      loadingMessage.value = `Generating slide ${i + 1} of ${titles.length}: ${slideTitle}`

      const slideBody: ChatStreamRequest = {
        repo_url: getRepoUrl(repoInfo),
        type: repoInfo.type,
        messages: [{
          role: 'user',
          content: buildSlidePrompt({ owner, repo, slideTitle, slideDescription, slideNumber: i + 1, totalSlides: titles.length, wikiContent }),
        }],
      }
      addTokensToRequestBody(slideBody, { token: repoInfo.token || '', provider, model, isCustomModel, customModel, language })
      const rawHtml = await streamChat(baseUrl, slideBody)
      built.push({ id: `slide-${i + 1}`, title: slideTitle, content: slideDescription || slideTitle, html: cleanSlideHtml(rawHtml, slideTitle) })
      slides.value = [...built]
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'An unknown error occurred'
  } finally {
    isLoading.value = false
    loadingMessage.value = undefined
  }
}

function nextSlide() { if (currentSlideIndex.value < slides.value.length - 1) currentSlideIndex.value++ }
function prevSlide() { if (currentSlideIndex.value > 0) currentSlideIndex.value-- }
function toggleFullscreen() { isFullscreen.value = !isFullscreen.value }

function exportSlides() {
  if (!slides.value.length) {
    exportError.value = 'No slides to export'
    return
  }
  try {
    isExporting.value = true
    exportError.value = null
    const body = slides.value.map((s) => `<div class="slide-container">${s.html}</div>`).join('\n')
    const html = `<!DOCTYPE html>
<html lang="${language}">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${repo} Slides</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.0.0/dist/mermaid.min.js"><\/script>
<style>
body{font-family:'Segoe UI',Tahoma,sans-serif;margin:0;background:#0d1117;color:#e6edf3;}
.slide-container{max-width:1280px;height:720px;margin:2rem auto;position:relative;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.5);border-radius:8px;}
@media print{.slide-container{page-break-after:always;margin:0;height:100vh;box-shadow:none;border-radius:0;}.nav-controls{display:none;}}
.nav-controls{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);display:flex;gap:20px;align-items:center;background:rgba(13,17,23,.8);padding:10px 20px;border-radius:30px;}
.nav-btn{background:rgba(56,139,253,.1);border:1px solid rgba(56,139,253,.4);color:#58a6ff;border-radius:50%;width:40px;height:40px;display:flex;align-items:center;justify-content:center;cursor:pointer;}
</style>
</head>
<body>
${body}
<div class="nav-controls">
  <div class="nav-btn" onclick="go(-1)"><i class="fas fa-chevron-left"></i></div>
  <div><span id="cur">1</span>/<span id="tot">${slides.value.length}</span></div>
  <div class="nav-btn" onclick="go(1)"><i class="fas fa-chevron-right"></i></div>
</div>
<script>
let i=0;const all=document.querySelectorAll('.slide-container');
function show(){all.forEach((s,k)=>s.style.display=k===i?'block':'none');document.getElementById('cur').textContent=i+1;}
function go(d){i=Math.max(0,Math.min(all.length-1,i+d));show();}
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key===' ')go(1);else if(e.key==='ArrowLeft')go(-1);});
window.onload=function(){show();if(typeof mermaid!=='undefined')mermaid.initialize({theme:'dark',securityLevel:'loose',startOnLoad:true});};
<\/script>
</body>
</html>`
    const blob = new Blob([html], { type: 'text/html' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${repo}_slides.html`
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

onMounted(() => {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === ' ') nextSlide()
    else if (e.key === 'ArrowLeft') prevSlide()
    else if (e.key === 'f' || e.key === 'F') toggleFullscreen()
    else if (e.key === 'Escape' && isFullscreen.value) isFullscreen.value = false
  }
  window.addEventListener('keydown', onKey)
  onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
  generate()
})
</script>

<template>
  <div class="min-h-screen flex flex-col" :class="isFullscreen ? 'fixed inset-0 z-50 bg-[#0d1117]' : 'bg-[var(--background)]'">
    <header v-if="!isFullscreen" class="sticky top-0 z-10 bg-[var(--card-bg)] border-b border-[var(--border-color)] shadow-sm">
      <div class="container mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-4">
          <NuxtLink :to="backTo" class="flex items-center text-[var(--foreground)] hover:text-[var(--accent-primary)] transition-colors">
            <UIcon name="i-fa6-solid-arrow-left" class="mr-2" />
            <span>返回 Wiki</span>
          </NuxtLink>
          <h1 class="text-xl font-bold text-[var(--accent-primary)]">Slides: {{ repo }}</h1>
        </div>
        <div class="flex items-center gap-2">
          <UButton color="primary" variant="soft" icon="i-fa6-solid-arrows-rotate" :loading="isLoading" square aria-label="Regenerate" @click="generate" />
          <UButton color="primary" variant="soft" icon="i-fa6-solid-download" :disabled="!slides.length || isExporting" square aria-label="Export" @click="exportSlides" />
          <UButton color="primary" variant="soft" icon="i-fa6-solid-expand" square aria-label="Fullscreen" @click="toggleFullscreen" />
        </div>
      </div>
    </header>

    <main class="flex-1 flex flex-col" :class="isFullscreen ? 'p-0' : 'container mx-auto px-4 py-6'">
      <div v-if="isLoading && !slides.length" class="flex flex-col items-center justify-center p-8 flex-grow">
        <div class="w-12 h-12 border-4 border-[var(--accent-primary)]/30 border-t-[var(--accent-primary)] rounded-full animate-spin mb-4" />
        <p class="text-[var(--foreground)]">{{ loadingMessage }}</p>
      </div>

      <UAlert v-else-if="error" color="error" variant="soft" title="Error" :description="error" />

      <div v-else-if="slides.length" class="flex flex-col flex-grow">
        <div
          class="flex-grow flex flex-col items-center justify-center"
          :class="isFullscreen ? 'p-0 bg-[#0d1117]' : 'bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg shadow-sm p-6 mb-4'"
        >
          <UAlert v-if="exportError" color="error" variant="soft" class="mb-4 w-full" :description="exportError" />
          <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css">
          <div class="flex items-center justify-center overflow-hidden" :class="isFullscreen ? 'w-full h-full' : 'w-full max-w-[1280px] aspect-[16/9]'">
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="w-full h-full" v-html="currentSlide?.html || ''" />
          </div>
        </div>

        <div class="flex items-center justify-between" :class="isFullscreen ? 'fixed bottom-6 left-1/2 -translate-x-1/2 bg-[#0d1117]/80 px-6 py-3 rounded-full z-10 shadow-lg' : 'mt-4'">
          <UButton color="primary" variant="soft" icon="i-fa6-solid-arrow-left" :disabled="currentSlideIndex === 0" square aria-label="Previous" @click="prevSlide" />
          <div class="text-[var(--foreground)]" :class="isFullscreen ? 'mx-4' : ''">Slide {{ currentSlideIndex + 1 }} / {{ slides.length }}</div>
          <UButton color="primary" variant="soft" icon="i-fa6-solid-arrow-right" :disabled="currentSlideIndex === slides.length - 1" square aria-label="Next" @click="nextSlide" />
          <UButton v-if="isFullscreen" class="ml-4" color="primary" variant="soft" icon="i-fa6-solid-xmark" square aria-label="Exit fullscreen" @click="toggleFullscreen" />
        </div>
      </div>

      <div v-else class="flex flex-col items-center justify-center p-8 flex-grow">
        <p class="text-[var(--foreground)]">No slides generated yet. Click regenerate to generate slides.</p>
      </div>
    </main>
  </div>
</template>
