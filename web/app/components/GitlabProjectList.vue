<script setup lang="ts">
// GitLab repo list using Nuxt UI UTable (search + table + status + pagination),
// consuming the BFF (/api/gitlab/projects, /api/wiki/projects).
import type { TableColumn } from '@nuxt/ui'

interface GitlabProject {
  pathWithNamespace: string
  name: string
  description?: string | null
  defaultBranch?: string
  starCount?: number
  webUrl?: string
}
interface ProcessedProject {
  owner: string
  repo: string
  repo_type: string
}
interface Row {
  p: GitlabProject
  owner: string
  repo: string
  isGenerated: boolean
  viewHref: string
  genHref: string
}

// Flatten a (possibly nested-group) GitLab path into a route- and cache-safe
// owner/repo pair: owner = first segment, repo = the rest joined with '_'. The
// backend cache filename recombines underscore parts back into `repo`, so this
// round-trips through save/load/processed_projects. The real URL is carried
// separately via repo_url (genHref) / the cached repo info.
function splitRepo(pathWithNamespace: string): { owner: string; repo: string } {
  const parts = pathWithNamespace.split('/')
  return { owner: parts[0] || '', repo: parts.slice(1).join('_') }
}

const searchInput = ref('')
const query = ref('')
const page = ref(1)

const projects = ref<GitlabProject[]>([])
const nextPage = ref<number | null>(null)
const generated = ref<Set<string>>(new Set())
const loading = ref(false)
const error = ref<string | null>(null)

async function loadGenerated() {
  try {
    const data = await $fetch<ProcessedProject[]>('/api/wiki/projects')
    if (!Array.isArray(data)) return
    const s = new Set<string>()
    for (const p of data) {
      if ((p.repo_type || '').toLowerCase().includes('gitlab')) {
        s.add(`${p.owner}/${p.repo}`.toLowerCase())
      }
    }
    generated.value = s
  } catch {
    /* best-effort */
  }
}

async function loadProjects() {
  loading.value = true
  error.value = null
  try {
    const qs = new URLSearchParams({ search: query.value, page: String(page.value) })
    const data = await $fetch<{ projects?: GitlabProject[]; nextPage?: number | null; error?: string }>(
      `/api/gitlab/projects?${qs.toString()}`,
    )
    if (data.error) error.value = data.error
    projects.value = data.projects || []
    nextPage.value = data.nextPage ?? null
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function submitSearch() {
  page.value = 1
  query.value = searchInput.value.trim()
}

onMounted(() => {
  loadGenerated()
  watch([query, page], loadProjects, { immediate: true })
})

const rows = computed<Row[]>(() =>
  projects.value.map((p) => {
    const { owner, repo } = splitRepo(p.pathWithNamespace)
    // Compare against the same flattened owner/repo key the backend stores.
    const isGenerated = generated.value.has(`${owner}/${repo}`.toLowerCase())
    const repoUrl = p.webUrl || ''
    const viewHref = `/${owner}/${repo}?type=gitlab&language=zh`
    const genParams = new URLSearchParams()
    genParams.append('type', 'gitlab')
    genParams.append('repo_url', encodeURIComponent(repoUrl))
    genParams.append('provider', 'openai')
    genParams.append('model', 'qwen-plus')
    genParams.append('language', 'zh')
    const genHref = `/${owner}/${repo}?${genParams.toString()}`
    return { p, owner, repo, isGenerated, viewHref, genHref }
  }),
)

const columns: TableColumn<Row>[] = [
  { accessorKey: 'path', header: '仓库路径' },
  { accessorKey: 'description', header: '仓库介绍' },
  { accessorKey: 'branch', header: '默认分支' },
  { accessorKey: 'status', header: '状态' },
  { id: 'actions', header: '操作', meta: { class: { th: 'text-right', td: 'text-right' } } },
]
</script>

<template>
  <div class="flex flex-col h-full min-h-0 p-4 sm:p-6">
    <form class="mb-4 shrink-0" @submit.prevent="submitSearch">
      <UInput
        v-model="searchInput"
        icon="i-lucide-search"
        size="lg"
        placeholder="搜索仓库(名称、路径或介绍),回车搜索…"
        class="w-full"
      />
    </form>

    <p v-if="error" class="mb-4 shrink-0 text-sm text-error">加载出错:{{ error }}</p>

    <UTable
      :data="rows"
      :columns="columns"
      :loading="loading"
      :empty="'没有仓库'"
      :sticky="true"
      class="flex-1 min-h-0 border border-default rounded-lg"
    >
      <template #path-cell="{ row }">
        <a
          v-if="row.original.p.webUrl"
          :href="row.original.p.webUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="font-mono text-primary hover:underline"
        >{{ row.original.p.pathWithNamespace }}</a>
        <span v-else class="font-mono">{{ row.original.p.pathWithNamespace }}</span>
      </template>

      <template #description-cell="{ row }">
        <span class="text-muted line-clamp-1 max-w-xs block" :title="row.original.p.description || ''">
          {{ row.original.p.description || '—' }}
        </span>
      </template>

      <template #branch-cell="{ row }">
        <span class="text-muted">{{ row.original.p.defaultBranch || '—' }}</span>
      </template>

      <template #status-cell="{ row }">
        <UBadge v-if="row.original.isGenerated" color="success" variant="soft" size="sm" label="已生成" />
        <UBadge v-else color="neutral" variant="outline" size="sm" label="未生成" />
      </template>

      <template #actions-cell="{ row }">
        <UButton v-if="row.original.isGenerated" :to="row.original.viewHref" color="primary" variant="solid" size="xs" label="查看" />
        <UButton v-else :to="row.original.genHref" color="primary" variant="outline" size="xs" label="生成" />
      </template>
    </UTable>

    <div v-if="!query" class="flex items-center justify-end gap-3 mt-4 shrink-0 text-sm text-muted">
      <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-chevron-left" :disabled="page <= 1 || loading" label="上一页" @click="page = Math.max(1, page - 1)" />
      <span>第 {{ page }} 页</span>
      <UButton color="neutral" variant="ghost" size="sm" trailing-icon="i-lucide-chevron-right" :disabled="!nextPage || loading" label="下一页" @click="page = page + 1" />
    </div>
  </div>
</template>
