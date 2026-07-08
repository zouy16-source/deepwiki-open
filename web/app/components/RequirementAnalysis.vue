<script setup lang="ts">
// AI 可行性分析卡片（FR-ANA，W5）：发起分析任务 → 轮询进度 → 回调完成后展示报告。
// 任务在 api 服务执行；成功回调会驱动 analysis_done 流转（详情页收到 changed 后刷新状态）。
import type { AnalysisRun, Requirement } from '~/types/requirement'

const props = defineProps<{ requirement: Requirement }>()
const emit = defineEmits<{ changed: [] }>()

const toast = useToast()
const { displayName } = usePlatformUsers()

const { data: runs, refresh: refreshRuns } = useFetch<AnalysisRun[]>(
  () => `/api/requirements/${props.requirement.id}/analysis`,
  { default: () => [], watch: [() => props.requirement.id] },
)

const latest = computed(() => runs.value?.[0] || null)
const activeRun = computed(() =>
  latest.value && (latest.value.status === 'queued' || latest.value.status === 'running') ? latest.value : null,
)
const canStart = computed(() => props.requirement.status === 'pending_analysis' && !activeRun.value)

const STATUS_BADGE: Record<AnalysisRun['status'], { label: string, color: string }> = {
  queued: { label: '排队中', color: 'warning' },
  running: { label: '分析中', color: 'primary' },
  succeeded: { label: '分析完成', color: 'success' },
  failed: { label: '分析失败', color: 'error' },
}

// 有进行中任务时每 3s 轮询；到达终态后通知父组件刷新需求状态与流转记录
let timer: ReturnType<typeof setInterval> | null = null
watch(activeRun, (cur, prev) => {
  if (cur && !timer) {
    timer = setInterval(() => { refreshRuns() }, 3000)
  } else if (!cur && timer) {
    clearInterval(timer)
    timer = null
    if (prev) {
      emit('changed')
      const done = runs.value?.find(r => r.id === prev.id)
      if (done?.status === 'succeeded') {
        toast.add({ title: 'AI 分析完成', description: done.summary || '报告已生成', color: 'success' })
      } else if (done?.status === 'failed') {
        toast.add({ title: 'AI 分析失败', description: done.error || '可使用人工降级流转', color: 'error' })
      }
    }
  }
}, { immediate: true })
onUnmounted(() => { if (timer) clearInterval(timer) })

const starting = ref(false)
async function startAnalysis() {
  if (starting.value) return
  starting.value = true
  try {
    await $fetch(`/api/requirements/${props.requirement.id}/analysis`, { method: 'POST' })
    toast.add({ title: 'AI 分析已发起', description: '任务执行中，完成后自动更新需求状态', color: 'info' })
    await refreshRuns()
  } catch (e: any) {
    toast.add({ title: '发起分析失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    starting.value = false
  }
}

const expandedReport = ref<number | null>(null)
watch(latest, (l) => {
  // 最新一次成功的报告默认展开
  if (l?.status === 'succeeded' && expandedReport.value === null) expandedReport.value = l.id
})
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium text-highlighted">AI 可行性分析 {{ runs?.length ? `· ${runs.length}` : '' }}</span>
        <UButton
          v-if="canStart"
          size="xs"
          icon="i-lucide-sparkles"
          :loading="starting"
          @click="startAnalysis"
        >
          开始 AI 分析
        </UButton>
      </div>
    </template>

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
          <UBadge v-if="run.complexity" :label="`复杂度 ${run.complexity}`" color="info" variant="outline" size="sm" />
          <span class="text-xs text-muted">
            <span :title="run.created_by">{{ displayName(run.created_by) }}</span> 发起于 {{ fmtTime(run.created_at) }}
            <template v-if="run.finished_at"> · 完成于 {{ fmtTime(run.finished_at) }}</template>
          </span>
          <UButton
            v-if="run.report_md"
            variant="link"
            color="neutral"
            size="xs"
            class="ml-auto"
            :trailing-icon="expandedReport === run.id ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
            @click="expandedReport = expandedReport === run.id ? null : run.id"
          >
            报告
          </UButton>
        </div>

        <p v-if="run.summary" class="text-sm text-highlighted">{{ run.summary }}</p>

        <UAlert
          v-if="run.status === 'failed'"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          title="分析失败"
          :description="`${run.error || '未知错误'}（可重新发起，或使用「手动标记分析完成（降级）」继续流转）`"
        />

        <div
          v-if="expandedReport === run.id && run.report_md"
          class="report-viewer bg-elevated/50 rounded p-4 max-h-[32rem] overflow-y-auto overflow-x-hidden"
        >
          <Markdown :content="run.report_md" class="text-sm" />
        </div>
      </div>
    </div>

    <p v-else class="text-sm text-muted">
      <template v-if="requirement.status === 'pending_analysis'">尚未发起分析，点击右上角「开始 AI 分析」。</template>
      <template v-else-if="requirement.status === 'draft'">需求提交分析后可发起 AI 分析。</template>
      <template v-else>暂无分析记录。</template>
    </p>
  </UCard>
</template>

<style scoped>
/* 报告里的长文件路径引用：允许任意断行，代码块/表格自身横滚（与对话气泡同一套防溢出策略） */
.report-viewer {
  overflow-wrap: anywhere;
}

.report-viewer :deep(code) {
  max-width: 100%;
  white-space: pre-wrap;
  word-break: break-all;
}

.report-viewer :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
}

.report-viewer :deep(pre code) {
  white-space: pre;
  word-break: normal;
}

.report-viewer :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
</style>
