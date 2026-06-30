<script setup lang="ts">
// Ported from src/components/GitlabProjectList.tsx.
// GitLab repo list: search + table + status + pagination, consuming the BFF
// (/api/gitlab/projects, /api/wiki/projects). @nuxt/ui for input/button/badge.

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

function splitRepo(pathWithNamespace: string): { owner: string; repo: string } {
  const parts = pathWithNamespace.split('/')
  return { owner: parts[0] || '', repo: parts.slice(1).join('/') }
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

const rows = computed(() =>
  projects.value.map((p) => {
    const { owner, repo } = splitRepo(p.pathWithNamespace)
    const isGenerated = generated.value.has(p.pathWithNamespace.toLowerCase())
    const repoUrl = p.webUrl || ''
    const viewHref = `/${owner}/${repo}?type=gitlab&language=zh`
    const genParams = new URLSearchParams()
    genParams.append('type', 'gitlab')
    genParams.append('repo_url', encodeURIComponent(repoUrl))
    genParams.append('provider', 'openai')
    genParams.append('model', 'qwen-plus')
    genParams.append('language', 'zh')
    const genHref = `/${owner}/${repo}?${genParams.toString()}`
    const nested = repo.includes('/')
    return { p, owner, repo, isGenerated, viewHref, genHref, nested }
  }),
)
</script>

<template>
  <div>
    <form class="mb-4" @submit.prevent="submitSearch">
      <UInput
        v-model="searchInput"
        icon="i-fa6-solid-magnifying-glass"
        size="lg"
        placeholder="搜索仓库(名称、路径或介绍),回车搜索…"
        :ui="{ root: 'w-full' }"
      />
    </form>

    <p v-if="error" class="mb-4 text-sm text-[var(--highlight)]">加载出错:{{ error }}</p>

    <div class="overflow-x-auto border border-[var(--border-color)] rounded-lg">
      <table class="min-w-full text-sm">
        <thead class="bg-[var(--background)] text-left text-[var(--muted)]">
          <tr>
            <th class="px-4 py-3 font-medium">仓库路径</th>
            <th class="px-4 py-3 font-medium">仓库介绍</th>
            <th class="px-4 py-3 font-medium">默认分支</th>
            <th class="px-4 py-3 font-medium">状态</th>
            <th class="px-4 py-3 font-medium text-right">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--border-color)]">
          <tr v-if="loading">
            <td colspan="5" class="px-4 py-8 text-center text-[var(--muted)]">加载中…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-[var(--muted)]">没有仓库</td>
          </tr>
          <template v-else>
            <tr v-for="r in rows" :key="r.p.pathWithNamespace" class="hover:bg-[var(--card-bg)] align-top">
              <td class="px-4 py-3 font-mono">
                <a v-if="r.p.webUrl" :href="r.p.webUrl" target="_blank" rel="noopener noreferrer" class="text-[var(--link-color)] hover:underline">{{ r.p.pathWithNamespace }}</a>
                <span v-else class="text-[var(--foreground)]">{{ r.p.pathWithNamespace }}</span>
              </td>
              <td class="px-4 py-3 text-[var(--muted)] max-w-xs truncate" :title="r.p.description || ''">{{ r.p.description || '—' }}</td>
              <td class="px-4 py-3 text-[var(--muted)]">{{ r.p.defaultBranch || '—' }}</td>
              <td class="px-4 py-3">
                <UBadge v-if="r.isGenerated" color="success" variant="soft" size="sm" label="已生成" />
                <UBadge v-else color="neutral" variant="outline" size="sm" label="未生成" />
              </td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <span v-if="r.nested" class="text-xs text-[var(--muted)]" title="deepwiki 路由暂不支持多层嵌套组">嵌套组暂不支持</span>
                <UButton v-else-if="r.isGenerated" :to="r.viewHref" color="primary" variant="solid" size="xs" label="查看" />
                <UButton v-else :to="r.genHref" color="primary" variant="outline" size="xs" label="生成" />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div v-if="!query" class="flex items-center justify-end gap-3 mt-4 text-sm text-[var(--muted)]">
      <UButton color="neutral" variant="ghost" size="sm" :disabled="page <= 1 || loading" label="← 上一页" @click="page = Math.max(1, page - 1)" />
      <span>第 {{ page }} 页</span>
      <UButton color="neutral" variant="ghost" size="sm" :disabled="!nextPage || loading" label="下一页 →" @click="page = page + 1" />
    </div>
  </div>
</template>
