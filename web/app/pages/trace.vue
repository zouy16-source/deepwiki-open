<script setup lang="ts">
// P0 字段追溯 v2：业务字段/术语 → 同系统多仓库 agent tool-loop 深挖（面向产品经理）。
// 走 NDJSON 流式端点实时展示工具调用；成功的追溯后端自动归档，此页可回看历史/导出。
definePageMeta({ layout: 'home' })

interface Profile { system?: string | null }
interface TraceStep { tool: string, args: string, result: string }
interface RepoTrace { repo: string, layer?: string, steps: TraceStep[], status: 'pending' | 'running' | 'done' }
interface TraceEvent {
  type: string, repos?: string[], repo?: string, layer?: string,
  tool?: string, args?: string, result?: string,
  markdown?: string, trace?: { repo: string, layer?: string, steps: TraceStep[] }[],
  detail?: string, report_id?: string
}
interface ReportMeta { id: string, system: string, query: string, created_at: number, repos: string[], steps: number }

const systems = ref<string[]>([])
const system = ref('')
const query = ref('')
const running = ref(false)
const phase = ref<'tracing' | 'synthesizing' | ''>('')
const error = ref<string | null>(null)
const result = ref('')
const repos = ref<string[]>([])
const trace = ref<RepoTrace[]>([])
const showTrace = ref(false)
const history = ref<ReportMeta[]>([])
const showHistory = ref(false)
const currentReportId = ref('')

onMounted(async () => {
  loadHistory()
  try {
    const profs = await $fetch<Record<string, Profile>>('/api/project/profiles')
    systems.value = [...new Set(Object.values(profs || {}).map(p => p.system).filter(Boolean))] as string[]
    if (systems.value[0]) system.value = systems.value[0]
  } catch { /* best-effort */ }
})

async function loadHistory() {
  try {
    history.value = await $fetch<ReportMeta[]>('/api/trace_reports', { query: { limit: 30 } })
  } catch { /* best-effort */ }
}

async function openReport(id: string) {
  try {
    const d = await $fetch<{ system: string, query: string, markdown: string, repos: string[], trace: RepoTrace[] }>(`/api/trace_reports/${id}`)
    if (d.system && systems.value.includes(d.system)) system.value = d.system
    query.value = d.query
    result.value = d.markdown
    repos.value = d.repos || []
    trace.value = (d.trace || []).map(t => ({ ...t, status: 'done' as const }))
    currentReportId.value = id
    showTrace.value = false
    showHistory.value = false
    error.value = null
  } catch {
    error.value = '报告加载失败'
  }
}

async function removeReport(id: string) {
  try {
    await $fetch(`/api/trace_reports/${id}`, { method: 'DELETE' })
    history.value = history.value.filter(h => h.id !== id)
  } catch { /* best-effort */ }
}

function exportMd() {
  const blob = new Blob([result.value], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${query.value.trim() || 'trace'}-全域逻辑梳理.md`
  a.click()
  URL.revokeObjectURL(a.href)
}

function fmtTime(ms: number) {
  const d = new Date(ms)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function repoOf(name?: string): RepoTrace | undefined {
  return trace.value.find(t => t.repo === name)
}

function handleEvent(ev: TraceEvent) {
  switch (ev.type) {
    case 'start':
      repos.value = ev.repos || []
      trace.value = repos.value.map(r => ({ repo: r, steps: [], status: 'pending' }))
      break
    case 'repo_start': {
      const t = repoOf(ev.repo)
      if (t) { t.status = 'running'; t.layer = ev.layer }
      break
    }
    case 'step':
      repoOf(ev.repo)?.steps.push({ tool: ev.tool || '', args: ev.args || '', result: ev.result || '' })
      break
    case 'repo_done': {
      const t = repoOf(ev.repo)
      if (t) t.status = 'done'
      break
    }
    case 'synthesizing':
      phase.value = 'synthesizing'
      break
    case 'result':
      result.value = ev.markdown || ''
      trace.value = (ev.trace || []).map(t => ({ ...t, status: 'done' as const }))
      currentReportId.value = ev.report_id || ''
      showTrace.value = false // 报告到手，过程收起（仍可展开回看）
      loadHistory() // 后端已自动归档
      break
    case 'error':
      error.value = ev.detail || '追溯失败'
      break
    // ping：心跳，忽略
  }
}

async function run() {
  if (!system.value || !query.value.trim() || running.value) return
  running.value = true
  phase.value = 'tracing'
  error.value = null
  result.value = ''
  repos.value = []
  trace.value = []
  showTrace.value = true // 运行中实时滚动展示调查过程
  showHistory.value = false
  try {
    const res = await fetch('/api/field_trace/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system: system.value, query: query.value.trim() }),
    })
    if (!res.ok || !res.body) {
      let detail = ''
      try { detail = (await res.json())?.detail } catch { /* non-JSON error body */ }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim()
        buf = buf.slice(nl + 1)
        if (line) handleEvent(JSON.parse(line) as TraceEvent)
      }
    }
    if (!result.value && !error.value) error.value = '连接中断，未收到结果'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '追溯失败'
  } finally {
    running.value = false
    phase.value = ''
  }
}
</script>

<template>
  <div class="h-full overflow-y-auto p-6">
    <div class="max-w-4xl mx-auto space-y-4">
      <div>
        <h1 class="text-xl font-bold text-default">业务字段追溯</h1>
        <p class="text-sm text-muted mt-1">输入业务字段或术语（如：运费 / inFeeAmt），AI agent 逐仓库深挖代码（grep→读源码→追调用链），梳理全域业务逻辑。</p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <label class="flex items-center gap-1.5 text-sm text-muted">系统
          <USelectMenu v-model="system" :items="systems" size="sm" class="w-44" />
        </label>
        <UInput v-model="query" size="sm" class="flex-1 min-w-[200px]" placeholder="业务字段/术语，如：运费" @keyup.enter="run" />
        <UButton
          color="primary" size="sm" icon="i-lucide-radar" :loading="running"
          :label="running ? (phase === 'synthesizing' ? '综合梳理中…' : '深挖代码中…') : '开始追溯'"
          @click="run"
        />
        <UButton
          v-if="history.length" size="sm" color="neutral" variant="ghost" icon="i-lucide-history"
          :label="`历史（${history.length}）`" @click="showHistory = !showHistory"
        />
      </div>
      <div v-if="showHistory" class="border border-default rounded-lg bg-elevated divide-y divide-default">
        <div
          v-for="h in history" :key="h.id"
          class="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-accented/50"
          :class="h.id === currentReportId && 'bg-accented/50'"
          @click="openReport(h.id)"
        >
          <span class="font-medium text-default truncate">{{ h.query }}</span>
          <UBadge color="neutral" variant="soft" size="sm" :label="h.system" />
          <span class="text-xs text-muted whitespace-nowrap ml-auto">{{ h.repos.length }} 仓库 · {{ h.steps }} 步 · {{ fmtTime(h.created_at) }}</span>
          <UButton
            size="xs" color="error" variant="ghost" icon="i-lucide-trash-2"
            @click.stop="removeReport(h.id)"
          />
        </div>
      </div>
      <p v-if="error" class="text-sm text-error">{{ error }}</p>
      <div v-if="repos.length" class="flex gap-1 flex-wrap text-xs text-muted items-center">
        覆盖仓库：<UBadge v-for="r in repos" :key="r" color="neutral" variant="soft" size="sm" :label="r" />
        <UButton
          v-if="!running && trace.some(t => t.steps.length)" size="xs" color="neutral" variant="ghost"
          :icon="showTrace ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
          :label="`调查过程（${trace.reduce((n, t) => n + t.steps.length, 0)} 次工具调用）`"
          @click="showTrace = !showTrace"
        />
        <UButton
          v-if="result" size="xs" color="neutral" variant="ghost" icon="i-lucide-download"
          label="导出 MD" @click="exportMd"
        />
      </div>
      <div v-if="showTrace" class="space-y-3">
        <div v-for="t in trace" :key="t.repo" class="border border-default rounded-lg p-3 bg-elevated">
          <p class="text-xs font-semibold text-default mb-1.5 flex items-center gap-1.5">
            <UIcon
              :name="t.status === 'done' ? 'i-lucide-check-circle-2' : t.status === 'running' ? 'i-lucide-loader-circle' : 'i-lucide-circle-dashed'"
              :class="['size-3.5', t.status === 'done' ? 'text-success' : 'text-muted', t.status === 'running' && 'animate-spin text-primary']"
            />
            {{ t.repo }}<span v-if="t.layer" class="text-muted font-normal">（{{ t.layer }}）</span>
            <span v-if="t.status === 'running'" class="text-muted font-normal">调查中…</span>
          </p>
          <p v-if="!t.steps.length" class="text-xs text-muted">{{ t.status === 'pending' ? '等待开始…' : '（未调用工具）' }}</p>
          <ol v-else class="space-y-1">
            <li v-for="(s, i) in t.steps" :key="i" class="text-xs font-mono text-muted truncate">
              <span class="text-primary">{{ s.tool }}</span>({{ s.args }}) → {{ s.result }}
            </li>
          </ol>
        </div>
        <p v-if="phase === 'synthesizing'" class="text-xs text-muted flex items-center gap-1.5">
          <UIcon name="i-lucide-loader-circle" class="size-3.5 animate-spin text-primary" />正在综合各仓库调查结果，生成全域梳理报告…
        </p>
      </div>
      <div v-if="result" class="border border-default rounded-lg p-5 bg-elevated">
        <Markdown :content="result" />
      </div>
    </div>
  </div>
</template>
