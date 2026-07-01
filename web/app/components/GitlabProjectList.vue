<script setup lang="ts">
// GitLab repo list using Nuxt UI UTable. «生成» now starts a background job on the
// backend (POST /api/wiki/generate) instead of navigating to the detail page; the
// list polls /api/wiki/jobs and shows live progress (phase + bar + ETA) per repo.
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
interface Job {
  id: string
  key: { owner: string; repo: string; repo_type: string; language: string; comprehensive: boolean }
  status: 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'canceled'
  phase: string | null
  progress: { percent: number; total_pages: number | null; done_pages: number; failed_pages: number; current_page: string | null }
  timing: { eta_seconds: number | null; elapsed_seconds: number }
  queue_position: number | null
  cache_ready: boolean
  error: { code: string; message: string } | null
}
interface Row {
  p: GitlabProject
  owner: string
  repo: string
  isGenerated: boolean
  viewHref: string
  job?: Job
}

// Flatten a (possibly nested-group) GitLab path into a route- and cache-safe
// owner/repo pair: owner = first segment, repo = the rest joined with '_'. The
// backend cache filename recombines underscore parts back into `repo`, so this
// round-trips through save/load/processed_projects. The real URL is carried
// separately via repo_url / the cached repo info.
function splitRepo(pathWithNamespace: string): { owner: string; repo: string } {
  const parts = pathWithNamespace.split('/')
  return { owner: parts[0] || '', repo: parts.slice(1).join('_') }
}
function keyOf(owner: string, repo: string) {
  return `${owner}/${repo}`.toLowerCase()
}

const toast = useToast()
const searchInput = ref('')
const query = ref('')
const page = ref(1)

interface UpdateStatus {
  status: 'up_to_date' | 'behind' | 'unknown'
  behind_count?: number | null
}

const projects = ref<GitlabProject[]>([])
const nextPage = ref<number | null>(null)
const generated = ref<Set<string>>(new Set())
const jobs = ref<Map<string, Job>>(new Map())
const updateStatus = ref<Map<string, UpdateStatus>>(new Map())
const loading = ref(false)
const error = ref<string | null>(null)

const ACTIVE = ['queued', 'running']

async function loadGenerated() {
  try {
    const data = await $fetch<ProcessedProject[]>('/api/wiki/projects')
    if (!Array.isArray(data)) return
    const s = new Set<string>()
    for (const p of data) {
      if ((p.repo_type || '').toLowerCase().includes('gitlab')) s.add(keyOf(p.owner, p.repo))
    }
    generated.value = s
  } catch {
    /* best-effort */
  }
}

// Lazily check, for each generated repo on the page, whether its wiki is behind
// the repo's latest commit (Phase A). Guarded so the job-poll re-renders don't refire.
const checkingStatus = new Set<string>()
function checkUpdateStatus() {
  for (const r of rows.value) {
    if (!r.isGenerated) continue
    const k = keyOf(r.owner, r.repo)
    if (updateStatus.value.has(k) || checkingStatus.has(k)) continue
    checkingStatus.add(k)
    $fetch<UpdateStatus>(
      `/api/wiki/update_status?owner=${encodeURIComponent(r.owner)}&repo=${encodeURIComponent(r.repo)}&repo_type=gitlab&language=zh`,
    )
      .then((s) => {
        const m = new Map(updateStatus.value)
        m.set(k, { status: s.status, behind_count: s.behind_count })
        updateStatus.value = m
      })
      .catch(() => {})
      .finally(() => checkingStatus.delete(k))
  }
}
function statusOf(row: Row): UpdateStatus | undefined {
  return updateStatus.value.get(keyOf(row.owner, row.repo))
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

// --- job polling ---
// Fast cadence while a job is active, a slow heartbeat when idle (so jobs started
// elsewhere / after a refresh still surface without a full remount).
let pollTimer: ReturnType<typeof setInterval> | null = null
let pollInterval = 0

function schedulePoll(ms: number) {
  if (pollTimer && pollInterval === ms) return
  stopPolling()
  pollInterval = ms
  pollTimer = setInterval(fetchJobs, ms)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; pollInterval = 0 }
}

const invalidatedJobs = new Set<string>()

async function fetchJobs() {
  try {
    const data = await $fetch<{ jobs: Job[] }>('/api/wiki/jobs')
    const m = new Map<string, Job>()
    const g = new Set(generated.value)
    let statusDirty = false
    for (const j of data.jobs || []) {
      const k = keyOf(j.key.owner, j.key.repo)
      m.set(k, j)
      if (j.cache_ready) {
        g.add(k) // persists past the job's TTL
        // A (re)generation / incremental update finished — re-check staleness once.
        if (!invalidatedJobs.has(j.id)) {
          invalidatedJobs.add(j.id)
          updateStatus.value.delete(k)
          statusDirty = true
        }
      }
    }
    jobs.value = m
    generated.value = g
    schedulePoll((data.jobs || []).some((j) => ACTIVE.includes(j.status)) ? 2500 : 10000)
    if (statusDirty) checkUpdateStatus()
  } catch {
    /* best-effort */
  }
}
function ensurePolling() {
  if (!pollTimer) schedulePoll(2500)
}

async function startGen(row: Row, force = false, mode: 'full' | 'incremental' = 'full') {
  try {
    const job = await $fetch<Job>('/api/wiki/generate', {
      method: 'POST',
      body: {
        owner: row.owner,
        repo: row.repo,
        repo_type: 'gitlab',
        language: 'zh',
        comprehensive: true,
        repo_url: row.p.webUrl || '',
        provider: 'openai',
        model: 'qwen-plus',
        mode,
        force,
      },
    })
    const m = new Map(jobs.value)
    m.set(keyOf(row.owner, row.repo), job)
    jobs.value = m
    if (job.cache_ready) generated.value = new Set(generated.value).add(keyOf(row.owner, row.repo))
    ensurePolling()
  } catch (e) {
    toast.add({ title: '启动生成失败', description: e instanceof Error ? e.message : String(e), color: 'error' })
  }
}

async function cancelGen(row: Row) {
  const j = jobs.value.get(keyOf(row.owner, row.repo))
  if (!j) return
  try {
    await $fetch(`/api/wiki/jobs/${j.id}`, { method: 'DELETE' })
  } catch { /* ignore */ }
  await fetchJobs()
}

function submitSearch() {
  page.value = 1
  query.value = searchInput.value.trim()
}

onMounted(() => {
  loadGenerated()
  fetchJobs()
  watch([query, page], loadProjects, { immediate: true })
  watch([generated, projects], checkUpdateStatus)
})
onBeforeUnmount(stopPolling)

const rows = computed<Row[]>(() =>
  projects.value.map((p) => {
    const { owner, repo } = splitRepo(p.pathWithNamespace)
    const k = keyOf(owner, repo)
    const job = jobs.value.get(k)
    const isGenerated = generated.value.has(k) || !!job?.cache_ready
    const viewHref = `/${owner}/${repo}?type=gitlab&language=zh`
    return { p, owner, repo, isGenerated, viewHref, job }
  }),
)

const columns: TableColumn<Row>[] = [
  { accessorKey: 'path', header: '仓库路径' },
  { accessorKey: 'description', header: '仓库介绍' },
  { accessorKey: 'branch', header: '默认分支' },
  { accessorKey: 'status', header: '状态', meta: { class: { th: 'w-52', td: 'w-52' } } },
  { id: 'actions', header: '操作', meta: { class: { th: 'text-right', td: 'text-right' } } },
]

const PHASE_LABEL: Record<string, string> = {
  fetching_repo: '拉取仓库',
  indexing: '索引中',
  planning: '规划结构',
  generating: '生成页面',
  saving: '保存中',
}
function isActive(job?: Job) {
  return !!job && ACTIVE.includes(job.status)
}
function statusText(job: Job): string {
  if (job.status === 'queued') return job.queue_position ? `排队中 (第 ${job.queue_position} 位)` : '排队中'
  return PHASE_LABEL[job.phase || ''] || '生成中'
}
function fmtEta(s: number | null): string {
  if (s == null) return ''
  if (s < 60) return `约 ${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  return sec ? `约 ${m}m${sec}s` : `约 ${m}m`
}
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
        <div v-if="isActive(row.original.job)" class="min-w-[10rem]">
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="text-primary truncate">{{ statusText(row.original.job!) }}</span>
            <span class="text-muted shrink-0 ml-2">{{ row.original.job!.progress.percent }}%</span>
          </div>
          <div class="h-1.5 bg-muted rounded-full overflow-hidden">
            <div class="h-full bg-primary rounded-full transition-all duration-500" :style="{ width: `${row.original.job!.progress.percent}%` }" />
          </div>
          <div class="flex items-center justify-between text-[11px] text-muted mt-1 h-4">
            <span v-if="row.original.job!.phase === 'generating' && row.original.job!.progress.total_pages" class="truncate">
              {{ row.original.job!.progress.done_pages }}/{{ row.original.job!.progress.total_pages }} 页
            </span>
            <span v-else />
            <span v-if="row.original.job!.timing.eta_seconds != null" class="shrink-0 ml-2">{{ fmtEta(row.original.job!.timing.eta_seconds) }}</span>
          </div>
        </div>
        <div v-else-if="row.original.isGenerated" class="flex flex-col items-start gap-1">
          <UBadge color="success" variant="soft" size="sm" label="已生成" />
          <UBadge
            v-if="statusOf(row.original)?.status === 'behind'"
            color="warning"
            variant="soft"
            size="xs"
            :label="`落后 ${statusOf(row.original)?.behind_count ?? '?'} 提交`"
          />
          <span v-else-if="statusOf(row.original)?.status === 'up_to_date'" class="text-[11px] text-muted">已是最新</span>
        </div>
        <UBadge
          v-else-if="row.original.job?.status === 'failed'"
          color="error"
          variant="soft"
          size="sm"
          label="失败"
          :title="row.original.job?.error?.message || ''"
        />
        <UBadge v-else color="neutral" variant="outline" size="sm" label="未生成" />
      </template>

      <template #actions-cell="{ row }">
        <UButton
          v-if="isActive(row.original.job)"
          color="neutral"
          variant="ghost"
          size="xs"
          icon="i-lucide-x"
          label="取消"
          @click="cancelGen(row.original)"
        />
        <div v-else-if="row.original.isGenerated" class="flex items-center justify-end gap-1">
          <UButton :to="row.original.viewHref" color="primary" variant="solid" size="xs" label="查看" />
          <UButton
            v-if="statusOf(row.original)?.status === 'behind'"
            color="warning"
            variant="soft"
            size="xs"
            icon="i-lucide-arrow-up-circle"
            label="增量更新"
            title="仅重生成受改动影响的页面"
            @click="startGen(row.original, false, 'incremental')"
          />
          <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-rotate-cw" title="重新生成(覆盖)" @click="startGen(row.original, true)" />
        </div>
        <UButton v-else-if="row.original.job?.status === 'failed'" color="error" variant="soft" size="xs" label="重试" @click="startGen(row.original)" />
        <UButton v-else color="primary" variant="outline" size="xs" label="生成" @click="startGen(row.original)" />
      </template>
    </UTable>

    <div v-if="!query" class="flex items-center justify-end gap-3 mt-4 shrink-0 text-sm text-muted">
      <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-chevron-left" :disabled="page <= 1 || loading" label="上一页" @click="page = Math.max(1, page - 1)" />
      <span>第 {{ page }} 页</span>
      <UButton color="neutral" variant="ghost" size="sm" trailing-icon="i-lucide-chevron-right" :disabled="!nextPage || loading" label="下一页" @click="page = page + 1" />
    </div>
  </div>
</template>
