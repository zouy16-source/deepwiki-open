<script setup lang="ts">
// GitLab repo card grid. «生成» starts a background job on the backend
// (POST /api/wiki/generate); the list polls /api/wiki/jobs and shows live progress
// (phase + bar + ETA) per repo. «AI 识别» does a light pre-scan (file tree + README,
// one LLM call, no clone) answering "这个系统是做什么的" and seeding later generation.

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

// --- generation confirm (full generation is long & costly; prevent misclicks) ---
const genConfirmOpen = ref(false)
const genPending = ref<{ row: Row, force: boolean, mode: 'full' | 'incremental' } | null>(null)

function genConfirmText(): string {
  const p = genPending.value
  if (!p) return ''
  if (p.mode === 'incremental')
    return `增量更新只重新生成受代码改动影响的页面，通常几分钟。确定更新「${p.row.p.name}」吗？`
  if (p.force)
    return `重新生成会覆盖「${p.row.p.name}」现有 wiki（手动编辑过的页面会保留），全流程约 10-20 分钟。确定继续吗？`
  return `生成完整 wiki 需要克隆仓库、建立索引并生成几十个页面，通常需要 10-20 分钟。确定开始生成「${p.row.p.name}」吗？`
}

function askGen(row: Row, force = false, mode: 'full' | 'incremental' = 'full') {
  genPending.value = { row, force, mode }
  genConfirmOpen.value = true
}

function confirmGen() {
  const p = genPending.value
  genConfirmOpen.value = false
  if (p) void startGen(p.row, p.force, p.mode)
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
  loadProfiles()
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

// --- AI pre-scan profiles ---
interface Profile {
  summary: string
  region?: string | string[] | null
  system?: string | null
  layer?: string | null
  domains?: string[]
  tech?: string[]
}
const profiles = ref<Map<string, Profile>>(new Map())
const scanning = ref<Set<string>>(new Set())

async function loadProfiles() {
  try {
    const data = await $fetch<Record<string, Profile>>('/api/project/profiles')
    profiles.value = new Map(Object.entries(data || {}))
  } catch { /* best-effort */ }
}

function profileOf(row: Row): Profile | undefined {
  return profiles.value.get(keyOf(row.owner, row.repo))
}

// --- profile-based filters (地区/系统/层次/业务域), AND-combined; 未识别项目在
// 任一筛选激活时隐藏（它们没有画像元数据）。
const ALL = '全部'
const regionFilter = ref(ALL)
const systemFilter = ref(ALL)
const layerFilter = ref(ALL)
const domainFilter = ref(ALL)

function regionsOf(pf?: Profile): string[] {
  const r = pf?.region
  return Array.isArray(r) ? r : (r ? String(r).split(/[,，、/]/).map((t) => t.trim()).filter(Boolean) : [])
}

const filterOptions = computed(() => {
  const regions = new Set<string>()
  const systems = new Set<string>()
  const layers = new Set<string>()
  const domains = new Set<string>()
  for (const r of rows.value) {
    const pf = profileOf(r)
    if (!pf) continue
    for (const rg of regionsOf(pf)) regions.add(rg)
    if (pf.system) systems.add(pf.system)
    if (pf.layer) layers.add(pf.layer)
    for (const d of pf.domains || []) domains.add(d)
  }
  return {
    regions: [ALL, ...regions],
    systems: [ALL, ...systems],
    layers: [ALL, ...layers],
    domains: [ALL, ...domains],
  }
})

const filterActive = computed(() =>
  [regionFilter, systemFilter, layerFilter, domainFilter].some((f) => f.value !== ALL),
)

const viewRows = computed(() => {
  if (!filterActive.value) return rows.value
  return rows.value.filter((r) => {
    const pf = profileOf(r)
    if (!pf) return false
    if (regionFilter.value !== ALL && !regionsOf(pf).includes(regionFilter.value)) return false
    if (systemFilter.value !== ALL && pf.system !== systemFilter.value) return false
    if (layerFilter.value !== ALL && pf.layer !== layerFilter.value) return false
    if (domainFilter.value !== ALL && !(pf.domains || []).includes(domainFilter.value)) return false
    return true
  })
})

async function scanProject(row: Row, silent = false): Promise<boolean> {
  const k = keyOf(row.owner, row.repo)
  if (scanning.value.has(k)) return false
  scanning.value = new Set(scanning.value).add(k)
  try {
    const p = await $fetch<Profile>('/api/project/profile', {
      method: 'POST',
      timeout: 270_000, // 大仓库文件树逐页拉取可能要几分钟
      body: { owner: row.owner, repo: row.repo, repo_type: 'gitlab', repo_url: row.p.webUrl || '' },
    })
    const m = new Map(profiles.value)
    m.set(k, p)
    profiles.value = m
    return true
  } catch (e) {
    if (!silent) {
      const detail = (e as { data?: { detail?: string } })?.data?.detail
      toast.add({ title: 'AI 识别失败', description: detail || (e instanceof Error ? e.message : String(e)), color: 'error' })
    }
    return false
  } finally {
    const s = new Set(scanning.value)
    s.delete(k)
    scanning.value = s
  }
}

// --- batch scan: all unprofiled repos on the current page, 3 at a time ---
const batchRunning = ref(false)
const batchDone = ref(0)
const batchTotal = ref(0)
async function batchScan() {
  if (batchRunning.value) return
  // 当页所有项目全部（重新）识别，已识别的也重扫（画像规则升级后可刷新存量）。
  const targets = rows.value.filter((r) => !scanning.value.has(keyOf(r.owner, r.repo)))
  if (!targets.length) return
  batchRunning.value = true
  batchTotal.value = targets.length
  batchDone.value = 0
  let ok = 0
  const queue = [...targets]
  const worker = async () => {
    for (;;) {
      const row = queue.shift()
      if (!row) return
      if (await scanProject(row, true)) ok++
      batchDone.value++
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker))
  batchRunning.value = false
  toast.add({
    title: '批量识别完成',
    description: `成功 ${ok} 个${ok < batchTotal.value ? `，失败 ${batchTotal.value - ok} 个` : ''}`,
    color: ok === batchTotal.value ? 'success' : 'warning',
  })
}

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
    <!-- 搜索 + 画像筛选（地区/系统/层次/业务域）+ 批量识别，同一行（窄屏自动换行） -->
    <div class="mb-4 shrink-0 flex items-center gap-2 flex-wrap">
      <form class="flex-1 min-w-[220px]" @submit.prevent="submitSearch">
        <UInput
          v-model="searchInput"
          icon="i-lucide-search"
          size="sm"
          placeholder="搜索仓库，回车搜索…"
          class="w-full"
        />
      </form>
      <label class="flex items-center gap-1 text-sm text-muted shrink-0">地区
        <USelectMenu v-model="regionFilter" :items="filterOptions.regions" size="sm" class="w-28" />
      </label>
      <label class="flex items-center gap-1 text-sm text-muted shrink-0">系统
        <USelectMenu v-model="systemFilter" :items="filterOptions.systems" size="sm" class="w-40" />
      </label>
      <label class="flex items-center gap-1 text-sm text-muted shrink-0">层次
        <USelectMenu v-model="layerFilter" :items="filterOptions.layers" size="sm" class="w-24" />
      </label>
      <label class="flex items-center gap-1 text-sm text-muted shrink-0">业务域
        <USelectMenu v-model="domainFilter" :items="filterOptions.domains" size="sm" class="w-32" />
      </label>
      <UButton
        v-if="filterActive" color="neutral" variant="ghost" size="xs" icon="i-lucide-x"
        title="清除筛选（筛选时未识别的项目会被隐藏）" aria-label="清除筛选" class="shrink-0"
        @click="regionFilter = systemFilter = layerFilter = domainFilter = ALL"
      />
      <UButton
        color="neutral" variant="outline" size="sm" icon="i-lucide-sparkles"
        :label="batchRunning ? `识别中 ${batchDone}/${batchTotal}` : `批量识别 (${rows.length})`"
        :loading="batchRunning"
        :disabled="!rows.length && !batchRunning"
        title="对本页所有项目（含已识别）重新执行 AI 识别（并发 3）"
        class="shrink-0"
        @click="batchScan"
      />
    </div>

    <p v-if="error" class="mb-4 shrink-0 text-sm text-error">加载出错:{{ error }}</p>

    <p v-if="loading" class="mb-4 shrink-0 text-sm text-muted">加载中…</p>
    <p v-else-if="!viewRows.length" class="mb-4 shrink-0 text-sm text-muted">{{ filterActive ? '没有符合筛选条件的项目' : '没有仓库' }}</p>

    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-4">
        <div
          v-for="row in viewRows" :key="row.p.pathWithNamespace"
          class="border border-default rounded-lg bg-elevated p-4 flex flex-col gap-2.5 hover:shadow-md hover:border-primary/40 transition-all"
        >
          <!-- 仓库名 + 状态徽章 -->
          <div class="flex items-start justify-between gap-2 min-w-0">
            <span class="font-semibold text-default leading-snug break-all">{{ row.p.name }}</span>
            <div class="shrink-0">
              <UBadge v-if="isActive(row.job)" color="primary" variant="soft" size="sm" label="生成中" />
              <UBadge v-else-if="row.isGenerated" color="success" variant="soft" size="sm" label="已生成" />
              <UBadge v-else-if="row.job?.status === 'failed'" color="error" variant="soft" size="sm" label="失败" :title="row.job?.error?.message || ''" />
              <UBadge v-else color="neutral" variant="outline" size="sm" label="未生成" />
            </div>
          </div>

          <!-- AI 识别结果 / 仓库介绍（固定最小高度，识别前后卡片高度一致） -->
          <div class="min-h-[4.25rem]">
            <template v-if="profileOf(row)">
              <p class="text-xs text-default leading-relaxed line-clamp-2" :title="profileOf(row)!.summary">
                <UIcon name="i-lucide-sparkles" class="text-primary inline-block align-text-top mr-0.5" />{{ profileOf(row)!.summary }}
              </p>
              <div class="flex gap-1 mt-1.5 overflow-hidden h-5">
                <UBadge v-for="rg in regionsOf(profileOf(row))" :key="rg" color="warning" variant="soft" size="sm" class="shrink-0" :label="rg" />
                <UBadge v-if="profileOf(row)!.system" color="primary" variant="soft" size="sm" class="shrink-0" :label="profileOf(row)!.system!" />
                <UBadge v-if="profileOf(row)!.layer" color="secondary" variant="soft" size="sm" class="shrink-0" :label="profileOf(row)!.layer!" />
                <UBadge v-for="d in (profileOf(row)!.domains || []).slice(0, 3)" :key="d" color="neutral" variant="soft" size="sm" class="shrink-0" :label="d" />
                <UBadge
                  v-if="(profileOf(row)!.domains || []).length > 3"
                  color="neutral" variant="soft" size="sm" class="shrink-0"
                  :label="`+${(profileOf(row)!.domains || []).length - 3}`"
                  :title="(profileOf(row)!.domains || []).slice(3).join('、')"
                />
              </div>
            </template>
            <p v-else class="text-xs text-muted line-clamp-2" :title="row.p.description || ''">
              {{ row.p.description || '暂无介绍，可用 AI 识别' }}
            </p>
          </div>

          <!-- git 路径 + 分支 + 更新状态 -->
          <div class="mt-auto pt-1 space-y-1.5 text-xs text-muted min-w-0">
            <a :href="row.p.webUrl || '#'" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1.5 hover:text-primary transition-colors min-w-0">
              <UIcon name="i-fa6-brands-gitlab" class="shrink-0" />
              <span class="truncate font-mono">{{ row.p.pathWithNamespace }}</span>
            </a>
            <div class="flex items-center gap-2">
              <span class="flex items-center gap-1"><UIcon name="i-lucide-git-branch" />{{ row.p.defaultBranch || '—' }}</span>
              <UBadge v-if="statusOf(row)?.status === 'behind'" color="warning" variant="soft" size="xs" :label="`落后 ${statusOf(row)?.behind_count ?? '?'} 提交`" />
              <span v-else-if="row.isGenerated && statusOf(row)?.status === 'up_to_date'">已是最新</span>
            </div>
          </div>

          <!-- 操作（生成中时进度条内联在本行，高度不变） -->
          <div class="flex items-center gap-1.5 pt-1 h-7">
            <template v-if="isActive(row.job)">
              <div
                class="flex-1 min-w-0 flex items-center gap-1.5 text-[11px]"
                :title="`${row.job!.phase === 'generating' && row.job!.progress.total_pages ? `${row.job!.progress.done_pages}/${row.job!.progress.total_pages} 页 · ` : ''}${row.job!.timing.eta_seconds != null ? fmtEta(row.job!.timing.eta_seconds) : ''}`"
              >
                <span class="text-primary truncate shrink-0 max-w-[5.5rem]">{{ statusText(row.job!) }}</span>
                <div class="flex-1 min-w-[2.5rem] h-1.5 bg-muted rounded-full overflow-hidden">
                  <div class="h-full bg-primary rounded-full transition-all duration-500" :style="{ width: `${row.job!.progress.percent}%` }" />
                </div>
                <span class="text-muted shrink-0">{{ row.job!.progress.percent }}%</span>
              </div>
              <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-x" title="取消生成" aria-label="取消生成" @click="cancelGen(row)" />
            </template>
            <UButton
              v-if="!isActive(row.job)"
              color="neutral" variant="outline" size="xs" icon="i-lucide-sparkles"
              :label="profileOf(row) ? '重新识别' : 'AI 识别'"
              :loading="scanning.has(keyOf(row.owner, row.repo))"
              title="AI 快速识别项目（文件树+README，不做完整索引）"
              @click="scanProject(row)"
            />
            <template v-if="!isActive(row.job) && row.isGenerated">
              <UButton :to="row.viewHref" color="primary" variant="solid" size="xs" label="查看" />
              <UButton
                v-if="statusOf(row)?.status === 'behind'"
                color="warning" variant="soft" size="xs" icon="i-lucide-arrow-up-circle" label="增量更新"
                title="仅重生成受改动影响的页面" @click="askGen(row, false, 'incremental')"
              />
              <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-rotate-cw" title="重新生成(覆盖)" @click="askGen(row, true)" />
            </template>
            <UButton v-else-if="!isActive(row.job) && row.job?.status === 'failed'" color="error" variant="soft" size="xs" label="重试" @click="askGen(row)" />
            <UButton v-else-if="!isActive(row.job)" color="primary" variant="outline" size="xs" label="生成" @click="askGen(row)" />
          </div>
        </div>
      </div>
    </div>

    <!-- 生成前确认（防误点：完整生成耗时长） -->
    <UModal v-model:open="genConfirmOpen" title="确认生成" :description="genConfirmText()">
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="取消" @click="genConfirmOpen = false" />
          <UButton color="primary" label="开始生成" icon="i-lucide-play" @click="confirmGen" />
        </div>
      </template>
    </UModal>

    <div v-if="!query" class="flex items-center justify-end gap-3 mt-4 shrink-0 text-sm text-muted">
      <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-chevron-left" :disabled="page <= 1 || loading" label="上一页" @click="page = Math.max(1, page - 1)" />
      <span>第 {{ page }} 页</span>
      <UButton color="neutral" variant="ghost" size="sm" trailing-icon="i-lucide-chevron-right" :disabled="!nextPage || loading" label="下一页" @click="page = page + 1" />
    </div>
  </div>
</template>
