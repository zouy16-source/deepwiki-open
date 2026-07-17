<script setup lang="ts">
// AI 编码卡片（FR-DEV-01）：发起编码任务 → dev 服务执行 → SSE 实时进度 → 出 GitLab MR。
// 成功回调驱动 coding_done 留痕并绑 MR 产物（详情页收到 changed 后刷新流转记录）。
import type { CodingRun, Requirement } from '~/types/requirement'

const props = defineProps<{ requirement: Requirement }>()
const emit = defineEmits<{ changed: [] }>()

const toast = useToast()
const { displayName } = usePlatformUsers()

const { data: runs, refresh: refreshRuns } = useFetch<CodingRun[]>(
  () => `/api/requirements/${props.requirement.id}/coding`,
  { default: () => [], watch: [() => props.requirement.id] },
)

const latest = computed(() => runs.value?.[0] || null)
const activeRun = computed(() =>
  latest.value && (latest.value.status === 'queued' || latest.value.status === 'running') ? latest.value : null,
)
// native 需求须处于「已排期」或「开发中」；TAPD 镜像需求随时可发起
const canStart = computed(() =>
  (props.requirement.source === 'tapd' || ['scheduled', 'in_dev'].includes(props.requirement.status)) && !activeRun.value,
)

const STATUS_BADGE: Record<CodingRun['status'], { label: string, color: string }> = {
  queued: { label: '排队中', color: 'warning' },
  running: { label: '编码中', color: 'primary' },
  succeeded: { label: '已出 MR', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

// 有进行中任务时每 3s 轮询状态（SSE 断线/刷新的兜底）；到终态通知父组件刷新流转记录
let timer: ReturnType<typeof setInterval> | null = null
watch(activeRun, (cur, prev) => {
  if (cur && !timer) {
    timer = setInterval(() => refreshRuns(), 3000)
  } else if (!cur && timer) {
    clearInterval(timer)
    timer = null
    if (prev) {
      emit('changed')
      const done = runs.value?.find(r => r.id === prev.id)
      if (done?.status === 'succeeded') {
        toast.add({ title: 'AI 编码完成', description: done.mr_url ? '已生成 MR，待人工 Review' : (done.summary || ''), color: 'success' })
      } else if (done?.status === 'failed') {
        toast.add({ title: 'AI 编码失败', description: done.error || '可重试', color: 'error' })
      }
    }
  }
}, { immediate: true })

// ---- 发起表单 ----
const showForm = ref(false)
const repoUrl = ref('')
const baseBranch = ref('')  // 留空 → 后端用仓库默认分支(repo_meta.default_branch,如 master)
const starting = ref(false)

// ---- SSE 实时进度 ----
interface ProgressLine { kind: string, message: string }
const progress = ref<ProgressLine[]>([])
const streamingRunId = ref<number | null>(null)
let es: EventSource | null = null

function closeStream() {
  if (es) { es.close(); es = null }
}
function openStream(runId: number) {
  closeStream()
  progress.value = []
  streamingRunId.value = runId
  es = new EventSource(`/api/coding/events?run_id=${runId}`)
  es.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data)
      if (d.kind === 'done') {
        closeStream()
        refreshRuns()
        setTimeout(() => refreshRuns(), 1500) // 等 dev→requirement 回调落库,同步 MR/状态
      } else {
        progress.value.push({ kind: d.kind, message: d.message })
      }
    } catch { /* 忽略非 JSON 行 */ }
  }
  es.onerror = () => closeStream()
}
onUnmounted(() => { closeStream(); if (timer) clearInterval(timer) })

async function startCoding() {
  if (starting.value) return
  starting.value = true
  try {
    const run = await $fetch<CodingRun>(`/api/requirements/${props.requirement.id}/coding`, {
      method: 'POST',
      body: {
        repo_url: repoUrl.value.trim() || undefined,       // 留空 → 后端从 repo_meta 自动解析
        base_branch: baseBranch.value.trim() || undefined, // 留空 → 后端用仓库默认分支
      },
    })
    showForm.value = false
    toast.add({ title: 'AI 编码已发起', description: '实时进度见下方', color: 'info' })
    await refreshRuns()
    openStream(run.id)
  } catch (e: any) {
    toast.add({ title: '发起编码失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    starting.value = false
  }
}

const KIND_ICON: Record<string, string> = {
  think: 'i-lucide-brain',
  tool: 'i-lucide-wrench',
  commit: 'i-lucide-git-commit-horizontal',
  push: 'i-lucide-upload',
  pr: 'i-lucide-git-pull-request',
  error: 'i-lucide-circle-alert',
  log: 'i-lucide-dot',
}
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium text-highlighted">AI 编码 {{ runs?.length ? `· ${runs.length}` : '' }}</span>
        <UButton
          v-if="canStart"
          size="xs"
          icon="i-lucide-bot"
          @click="showForm = true"
        >
          发起 AI 编码
        </UButton>
      </div>
    </template>

    <!-- 实时进度（本轮发起后 SSE 流） -->
    <div v-if="streamingRunId && progress.length" class="mb-3 border border-primary/40 rounded-lg p-3">
      <div class="flex items-center gap-2 mb-2 text-sm">
        <UIcon name="i-lucide-loader-circle" class="size-3.5 animate-spin text-primary" />
        <span class="text-highlighted font-medium">实时进度 · #{{ streamingRunId }}</span>
      </div>
      <div class="max-h-64 overflow-y-auto space-y-1 text-xs">
        <div v-for="(p, i) in progress" :key="i" class="flex gap-2" :class="p.kind === 'error' ? 'text-error' : 'text-muted'">
          <UIcon :name="KIND_ICON[p.kind] || 'i-lucide-dot'" class="size-3.5 shrink-0 mt-0.5" />
          <span class="whitespace-pre-wrap break-words">{{ p.message }}</span>
        </div>
      </div>
    </div>

    <div v-if="runs?.length" class="space-y-3">
      <div
        v-for="run in runs"
        :key="run.id"
        class="border border-default rounded-lg p-3 space-y-2"
        :class="run.status === 'queued' || run.status === 'running' ? 'border-primary/40' : ''"
      >
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-xs text-muted">#{{ run.id }}</span>
          <UBadge
            :label="STATUS_BADGE[run.status].label"
            :color="(STATUS_BADGE[run.status].color as any)"
            variant="subtle"
            size="sm"
          />
          <UIcon
            v-if="run.status === 'queued' || run.status === 'running'"
            name="i-lucide-loader-circle"
            class="size-3.5 animate-spin text-primary"
          />
          <span class="text-xs text-muted">
            <span :title="run.created_by">{{ displayName(run.created_by) }}</span> 发起于 {{ fmtTime(run.created_at) }}
            <template v-if="run.finished_at"> · 完成于 {{ fmtTime(run.finished_at) }}</template>
          </span>
          <UButton
            v-if="run.mr_url"
            variant="link"
            color="primary"
            size="xs"
            class="ml-auto"
            icon="i-lucide-git-pull-request"
            :to="run.mr_url"
            target="_blank"
          >
            查看 MR
          </UButton>
        </div>

        <p v-if="run.branch" class="text-xs text-muted">分支 <code class="text-highlighted">{{ run.branch }}</code></p>
        <p v-if="run.summary" class="text-sm text-highlighted whitespace-pre-wrap">{{ run.summary }}</p>

        <UAlert
          v-if="run.status === 'failed'"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          title="编码失败"
          :description="run.error || '未知错误（可重新发起）'"
        />
      </div>
    </div>

    <p v-else-if="!streamingRunId" class="text-sm text-muted">
      <template v-if="canStart">点击右上角「发起 AI 编码」，AI 将拉代码、改代码、跑测试并提交 MR。</template>
      <template v-else-if="requirement.source !== 'tapd'">需求进入「已排期」或「开发中」后可发起 AI 编码。</template>
      <template v-else>暂无编码记录。</template>
    </p>

    <!-- 发起表单 -->
    <UModal v-model:open="showForm" title="发起 AI 编码" description="AI 将 clone 目标仓库、按需求改代码、跑测试并向 GitLab 提交 MR。">
      <template #body>
        <div class="space-y-4">
          <UFormField label="目标仓库 git 地址" help="留空则用项目绑定库的地址（wiki 生成时已自动记录）；仅当项目绑定多个库时需指定">
            <UInput v-model="repoUrl" placeholder="留空自动解析（多仓库时填 https://git.ymdd.tech/组/仓库.git）" class="w-full" />
          </UFormField>
          <UFormField label="基分支" help="留空则用仓库默认分支（如 master）">
            <UInput v-model="baseBranch" placeholder="留空自动用仓库默认分支" class="w-full" />
          </UFormField>
          <UAlert
            color="warning"
            variant="subtle"
            icon="i-lucide-triangle-alert"
            title="起步直连 Claude API"
            description="当前 Worker 为 Claude Code Runtime，代码会发送至 Anthropic。敏感仓库请确认可出海。"
          />
        </div>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton variant="ghost" color="neutral" @click="showForm = false">取消</UButton>
          <UButton icon="i-lucide-bot" :loading="starting" @click="startCoding">发起</UButton>
        </div>
      </template>
    </UModal>
  </UCard>
</template>
