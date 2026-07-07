<script setup lang="ts">
// Generated-wiki list as a card grid, filterable by business system (全部/银河/未分组…).
// Data from /api/wiki/projects; per-card actions: 查看 / 删除 / 编辑系统信息.

interface WikiDoc {
  id: string
  owner: string
  repo: string
  name: string
  repo_type: string
  submittedAt: number
  language: string
  repo_url?: string
  title?: string | null        // wiki 生成的标题（如 银河运单系统）
  system?: string | null       // 所属业务系统（如 银河）
  layer?: string | null        // 前端/后端/小程序/网关…
  system_tags?: string[] | null
}

const UNGROUPED = '未分组'

const config = useRuntimeConfig()
const gitlabBase = config.public.gitlabBase || 'https://gitlab.com'
const toast = useToast()

function sourceUrl(d: WikiDoc): string {
  // Prefer the stored real URL — owner/repo can be a flattened nested-group path
  // ('_' joined), which can't be reconstructed back into the real URL.
  if (d.repo_url) return d.repo_url.replace(/^http:\/\//i, 'https://')
  const t = (d.repo_type || '').toLowerCase()
  if (t.includes('github')) return `https://github.com/${d.owner}/${d.repo}`
  if (t.includes('bitbucket')) return `https://bitbucket.org/${d.owner}/${d.repo}`
  return `${gitlabBase}/${d.owner}/${d.repo}`
}

function gitPath(d: WikiDoc): string {
  try {
    const u = new URL(sourceUrl(d))
    return u.pathname.replace(/^\//, '')
  } catch {
    return `${d.owner}/${d.repo}`
  }
}

function repoIcon(d: WikiDoc): string {
  const t = (d.repo_type || '').toLowerCase()
  if (t.includes('github')) return 'i-fa6-brands-github'
  if (t.includes('bitbucket')) return 'i-fa6-brands-bitbucket'
  return 'i-fa6-brands-gitlab'
}

// Route to the wiki detail page.
function wikiHref(d: WikiDoc): string {
  return `/${d.owner}/${d.repo}?type=${d.repo_type}&language=${d.language}`
}

const docs = ref<WikiDoc[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function fetchDocs() {
  loading.value = true
  error.value = null
  try {
    const data = await $fetch<WikiDoc[] | { error?: string }>('/api/wiki/projects')
    if (!Array.isArray(data)) throw new Error((data as { error?: string }).error || '加载失败')
    docs.value = data
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
    docs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchDocs)

// --- system filter (replaces the old text search) ---
const systemFilter = ref('全部')
const systems = computed(() => {
  const counts = new Map<string, number>()
  for (const d of docs.value) {
    const k = d.system?.trim() || UNGROUPED
    counts.set(k, (counts.get(k) || 0) + 1)
  }
  const names = [...counts.keys()].sort((a, b) => Number(a === UNGROUPED) - Number(b === UNGROUPED))
  return [
    { name: '全部', count: docs.value.length },
    ...names.map((n) => ({ name: n, count: counts.get(n) || 0 })),
  ]
})
const filtered = computed(() => {
  if (systemFilter.value === '全部') return docs.value
  return docs.value.filter((d) => (d.system?.trim() || UNGROUPED) === systemFilter.value)
})

// --- delete confirmation ---
const confirmOpen = ref(false)
const pending = ref<WikiDoc | null>(null)
const deleting = ref(false)

function askDelete(d: WikiDoc) {
  pending.value = d
  confirmOpen.value = true
}

async function confirmDelete() {
  const d = pending.value
  if (!d) return
  deleting.value = true
  try {
    await $fetch('/api/wiki/projects', {
      method: 'DELETE',
      body: { owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language },
    })
    docs.value = docs.value.filter((x) => x.id !== d.id)
    toast.add({ title: '已删除', description: d.name, color: 'success' })
    confirmOpen.value = false
  } catch (e) {
    const msg = e instanceof Error ? e.message : '未知错误'
    toast.add({ title: '删除失败', description: msg, color: 'error' })
  } finally {
    deleting.value = false
  }
}

// --- system meta editing ---
const metaOpen = ref(false)
const metaDoc = ref<WikiDoc | null>(null)
const metaForm = ref({ system: '', layer: '', tags: '' })
const savingMeta = ref(false)

function openMeta(d: WikiDoc) {
  metaDoc.value = d
  metaForm.value = { system: d.system || '', layer: d.layer || '', tags: (d.system_tags || []).join(', ') }
  metaOpen.value = true
}

async function saveMeta() {
  const d = metaDoc.value
  if (!d) return
  savingMeta.value = true
  try {
    const tags = metaForm.value.tags.split(/[,，、]/).map((t) => t.trim()).filter(Boolean)
    await $fetch('/api/wiki/system_meta', {
      method: 'PUT',
      body: {
        owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language,
        system: metaForm.value.system, layer: metaForm.value.layer, system_tags: tags,
      },
    })
    d.system = metaForm.value.system.trim() || null
    d.layer = metaForm.value.layer.trim() || null
    d.system_tags = tags
    docs.value = [...docs.value]
    toast.add({ title: '已保存系统信息', color: 'success' })
    metaOpen.value = false
  } catch (e) {
    toast.add({ title: '保存失败', description: e instanceof Error ? e.message : '未知错误', color: 'error' })
  } finally {
    savingMeta.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0 p-4 sm:p-6">
    <!-- System filter -->
    <div class="mb-4 shrink-0 flex items-center gap-2 flex-wrap">
      <UIcon name="i-lucide-boxes" class="text-primary shrink-0" />
      <UButton
        v-for="s in systems" :key="s.name"
        size="xs"
        :color="systemFilter === s.name ? 'primary' : 'neutral'"
        :variant="systemFilter === s.name ? 'soft' : 'ghost'"
        class="rounded-full"
        @click="systemFilter = s.name"
      >
        {{ s.name }}<span class="ml-1 opacity-60">{{ s.count }}</span>
      </UButton>
    </div>

    <p v-if="error" class="mb-4 shrink-0 text-sm text-error">加载出错:{{ error }}</p>
    <p v-if="loading" class="mb-4 shrink-0 text-sm text-muted">加载中…</p>
    <p v-else-if="!filtered.length" class="mb-4 shrink-0 text-sm text-muted">暂无已生成的 wiki 文档</p>

    <!-- Card grid -->
    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-4">
        <div
          v-for="d in filtered" :key="d.id"
          class="border border-default rounded-lg bg-elevated p-4 flex flex-col gap-2.5 hover:shadow-md hover:border-primary/40 transition-all group"
        >
          <!-- Title (wiki-generated) + favorite + meta edit -->
          <div class="flex items-start justify-between gap-1 min-w-0">
            <NuxtLink :to="wikiHref(d)" class="font-semibold text-default hover:text-primary leading-snug break-all">
              {{ d.title || d.repo }}
            </NuxtLink>
            <div class="flex items-center shrink-0">
              <!-- 收藏：占位按钮，收藏逻辑后续接入 -->
              <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-heart" aria-label="收藏" />
              <UButton
                color="neutral" variant="ghost" size="xs" icon="i-lucide-pencil"
                class="opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label="编辑系统信息" @click="openMeta(d)"
              />
            </div>
          </div>

          <!-- 系统 / 层次 / 业务域 -->
          <div class="flex flex-wrap gap-1">
            <UBadge v-if="d.system" color="primary" variant="soft" size="sm" :label="d.system" />
            <UBadge v-else color="neutral" variant="soft" size="sm" :label="UNGROUPED" />
            <UBadge v-if="d.layer" color="secondary" variant="soft" size="sm" :label="d.layer" />
            <UBadge v-for="tg in d.system_tags || []" :key="tg" color="neutral" variant="soft" size="sm" :label="tg" />
          </div>

          <!-- git path + time -->
          <div class="mt-auto pt-1 space-y-1.5 text-xs text-muted min-w-0">
            <a
              :href="sourceUrl(d)" target="_blank" rel="noopener noreferrer"
              class="flex items-center gap-1.5 hover:text-primary transition-colors min-w-0"
            >
              <UIcon :name="repoIcon(d)" class="shrink-0" />
              <span class="truncate font-mono">{{ gitPath(d) }}</span>
            </a>
            <div class="flex items-center gap-1.5">
              <UIcon name="i-lucide-clock" class="shrink-0" />
              <span>{{ new Date(d.submittedAt).toLocaleString() }}</span>
            </div>
          </div>

          <!-- actions -->
          <div class="flex gap-2 pt-1">
            <UButton :to="wikiHref(d)" color="primary" variant="solid" size="xs" icon="i-lucide-eye" label="查看" class="flex-1 justify-center" />
            <UButton color="error" variant="outline" size="xs" icon="i-lucide-trash-2" aria-label="删除" @click="askDelete(d)" />
          </div>
        </div>
      </div>
    </div>

    <UModal v-model:open="confirmOpen" title="确认删除" :description="pending ? `确定删除「${pending.name}」的 wiki 吗？此操作不可撤销。` : ''">
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="取消" :disabled="deleting" @click="confirmOpen = false" />
          <UButton color="error" variant="solid" label="删除" :loading="deleting" @click="confirmDelete" />
        </div>
      </template>
    </UModal>

    <!-- System meta editor -->
    <UModal v-model:open="metaOpen" title="编辑系统信息" :description="metaDoc ? metaDoc.name : ''">
      <template #body>
        <div class="space-y-3">
          <UFormField label="所属系统" help="相同系统名的仓库会归为同一业务系统（如：银河）">
            <UInput v-model="metaForm.system" placeholder="如：银河" class="w-full" />
          </UFormField>
          <UFormField label="层次">
            <UInput v-model="metaForm.layer" placeholder="前端 / 后端 / 小程序 / 网关…" class="w-full" />
          </UFormField>
          <UFormField label="业务域标签" help="逗号分隔">
            <UInput v-model="metaForm.tags" placeholder="运单, 面单" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="取消" :disabled="savingMeta" @click="metaOpen = false" />
          <UButton color="primary" label="保存" :loading="savingMeta" @click="saveMeta" />
        </div>
      </template>
    </UModal>
  </div>
</template>
