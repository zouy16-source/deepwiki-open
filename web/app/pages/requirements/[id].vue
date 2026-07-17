<script setup lang="ts">
// 需求详情（FR-REQ-02/03/04）：字段 + 状态流转操作 + 留痕时间线 + 主/子需求树。
import type { FlowEvent, Requirement } from '~/types/requirement'
import type { FlowAction } from '~/utils/requirementFlow'

definePageMeta({ layout: 'home' })

const route = useRoute()
const toast = useToast()
const { displayName } = usePlatformUsers()
const reqId = computed(() => Number(route.params.id))

const { data: req, refresh: refreshReq, error } = useFetch<Requirement>(
  () => `/api/requirements/${reqId.value}`,
)
const { data: events, refresh: refreshEvents } = useFetch<FlowEvent[]>(
  () => `/api/requirements/${reqId.value}/events`,
  { default: () => [] },
)
const { data: children, refresh: refreshChildren } = useFetch<Requirement[]>(
  '/api/requirements',
  { query: computed(() => ({ parent_id: reqId.value })), default: () => [] },
)
const { data: parent } = useFetch<Requirement>(
  () => `/api/requirements/${req.value?.parent_id}`,
  { immediate: false, watch: [() => req.value?.parent_id], default: () => null as Requirement | null },
)

// TAPD 镜像需求只读：不显示平台流转/评审/建子需求，改显示同步入口；但保留 AI 分析（增值）
const isTapd = computed(() => req.value?.source === 'tapd')

// start_review/approve/reject 由评审卡片（RequirementReviews）驱动，不在通用按钮出现
const actions = computed<FlowAction[]>(() =>
  isTapd.value
    ? []
    : (req.value ? allowedActions(req.value.status) : []).filter(a => !REVIEW_MANAGED_ACTIONS.has(a.action)),
)

async function onReviewChanged() {
  await Promise.all([refreshReq(), refreshEvents()])
}

// 从 TAPD 重新同步本需求所属项目（TAPD 侧改动后拉最新）
const syncing = ref(false)
async function resync() {
  if (!req.value || syncing.value) return
  syncing.value = true
  try {
    const res = await $fetch<{ created: number, updated: number }>('/api/tapd/sync', {
      method: 'POST',
      body: { project_id: req.value.project_id },
    })
    toast.add({ title: 'TAPD 同步完成', description: `更新 ${res.updated}、新增 ${res.created}`, color: 'success' })
    await Promise.all([refreshReq(), refreshEvents()])
  } catch (e: any) {
    toast.add({ title: '同步失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    syncing.value = false
  }
}

// 流转确认弹窗
const pendingAction = ref<FlowAction | null>(null)
const comment = ref('')
const transiting = ref(false)

function openAction(a: FlowAction) {
  pendingAction.value = a
  comment.value = ''
}

async function doTransition() {
  const a = pendingAction.value
  if (!a || transiting.value) return
  transiting.value = true
  try {
    await $fetch(`/api/requirements/${reqId.value}/transitions`, {
      method: 'POST',
      body: { action: a.action, comment: comment.value },
    })
    toast.add({ title: `已${a.label}`, description: `状态 → ${STATUS_META[a.to]?.label || a.to}`, color: 'success' })
    pendingAction.value = null
    await Promise.all([refreshReq(), refreshEvents()])
  } catch (e: any) {
    toast.add({ title: '流转失败', description: e?.data?.detail || e?.statusMessage || '请刷新后重试', color: 'error' })
  } finally {
    transiting.value = false
  }
}

const timeline = computed(() => [...(events.value || [])].reverse())
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-4xl mx-auto p-4 sm:p-6 space-y-5">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" title="需求不存在或加载失败">
        <template #actions>
          <UButton variant="link" color="error" to="/requirements">返回列表</UButton>
        </template>
      </UAlert>

      <template v-else-if="req">
        <!-- 头部：标题 + 状态 + 操作 -->
        <div class="space-y-3">
          <div class="flex items-center gap-2 text-sm text-muted">
            <UButton variant="ghost" color="neutral" icon="i-lucide-arrow-left" size="sm" to="/requirements" />
            <NuxtLink to="/requirements" class="hover:text-primary">需求管理</NuxtLink>
            <template v-if="parent">
              <UIcon name="i-lucide-chevron-right" class="size-3.5" />
              <NuxtLink :to="`/requirements/${parent.id}`" class="hover:text-primary truncate max-w-48">
                #{{ parent.id }} {{ parent.title }}
              </NuxtLink>
            </template>
            <UIcon name="i-lucide-chevron-right" class="size-3.5" />
            <span>#{{ req.id }}</span>
          </div>

          <div class="flex flex-wrap items-start gap-3">
            <h1 class="text-xl font-bold text-highlighted flex-1 min-w-60">{{ req.title }}</h1>
            <div class="flex flex-wrap gap-2">
              <template v-if="isTapd">
                <UButton
                  color="neutral"
                  variant="outline"
                  size="sm"
                  icon="i-lucide-external-link"
                  :to="req.external_url"
                  target="_blank"
                >
                  在 TAPD 打开
                </UButton>
                <UButton color="primary" size="sm" icon="i-lucide-refresh-cw" :loading="syncing" @click="resync">
                  同步
                </UButton>
              </template>
              <UButton
                v-for="a in actions"
                :key="a.action"
                :color="(a.color as any)"
                :variant="a.color === 'neutral' ? 'outline' : 'solid'"
                size="sm"
                @click="openAction(a)"
              >
                {{ a.label }}
              </UButton>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <UBadge :label="TYPE_LABELS[req.req_type]" :color="req.req_type === 'business' ? 'primary' : 'neutral'" variant="outline" />
            <UBadge v-if="isTapd" label="TAPD 只读镜像" color="warning" variant="soft" />
            <UBadge
              v-if="isTapd"
              :label="req.external_status || 'TAPD'"
              color="neutral"
              variant="subtle"
            />
            <UBadge v-else :label="STATUS_META[req.status]?.label || req.status" :color="(STATUS_META[req.status]?.color as any) || 'neutral'" variant="subtle" />
            <UBadge :label="req.priority" :color="(PRIORITY_COLORS[req.priority] as any)" variant="outline" />
            <UBadge v-if="req.complexity" :label="`复杂度 ${req.complexity}`" color="info" variant="outline" />
            <span class="text-xs text-muted ml-1">
              <template v-if="isTapd">
                处理人 <span :title="req.assignee">{{ displayName(req.assignee) }}</span>
                · 同步于 {{ fmtTime(req.synced_at) }}
              </template>
              <template v-else>
                <span :title="req.creator">{{ displayName(req.creator) }}</span> 创建于 {{ fmtTime(req.created_at) }} · 更新于 {{ fmtTime(req.updated_at) }}
                <template v-if="req.expected_online_date"> · 期望上线 {{ req.expected_online_date }}</template>
              </template>
            </span>
          </div>
        </div>

        <!-- 描述 -->
        <UCard>
          <template #header>
            <span class="text-sm font-medium text-highlighted">需求描述</span>
          </template>
          <p v-if="req.description" class="text-sm whitespace-pre-wrap leading-relaxed">{{ req.description }}</p>
          <p v-else class="text-sm text-muted">（未填写）</p>
        </UCard>

        <!-- AI 可行性分析（FR-ANA，W5） -->
        <RequirementAnalysis :requirement="req" @changed="onReviewChanged" />

        <!-- AI 编码（FR-DEV-01）：发起 → SSE 实时进度 → GitLab MR -->
        <RequirementCoding :requirement="req" @changed="onReviewChanged" />

        <!-- 评审（FR-REV-01/02）：TAPD 镜像需求在源系统评审，平台不代管 -->
        <RequirementReviews v-if="!isTapd" :requirement="req" @changed="onReviewChanged" />

        <!-- 子需求 -->
        <UCard>
          <template #header>
            <div class="flex items-center justify-between">
              <span class="text-sm font-medium text-highlighted">子需求（系统需求）{{ children?.length ? `· ${children.length}` : '' }}</span>
              <UButton v-if="!isTapd" size="xs" variant="soft" icon="i-lucide-plus" :to="`/requirements/new?parent=${req.id}`">
                新建子需求
              </UButton>
            </div>
          </template>
          <div v-if="children?.length" class="divide-y divide-default -my-2">
            <NuxtLink
              v-for="c in children"
              :key="c.id"
              :to="`/requirements/${c.id}`"
              class="flex items-center gap-3 py-2.5 hover:bg-elevated/50 -mx-2 px-2 rounded transition-colors"
            >
              <span class="text-xs text-muted shrink-0">#{{ c.id }}</span>
              <span class="text-sm font-medium text-highlighted truncate flex-1">{{ c.title }}</span>
              <UBadge :label="STATUS_META[c.status]?.label || c.status" :color="(STATUS_META[c.status]?.color as any) || 'neutral'" variant="subtle" size="sm" />
              <UBadge :label="c.priority" :color="(PRIORITY_COLORS[c.priority] as any)" variant="outline" size="sm" />
            </NuxtLink>
          </div>
          <p v-else class="text-sm text-muted">暂无子需求。业务需求评审排期后拆分为系统需求。</p>
        </UCard>

        <!-- 流转留痕 -->
        <UCard>
          <template #header>
            <span class="text-sm font-medium text-highlighted">流转记录 · {{ timeline.length }}</span>
          </template>
          <ol class="space-y-0">
            <li v-for="(e, i) in timeline" :key="e.id" class="relative flex gap-3 pb-4 last:pb-0">
              <div class="flex flex-col items-center">
                <span
                  class="size-2.5 rounded-full mt-1.5 shrink-0"
                  :class="i === 0 ? 'bg-primary' : 'bg-accented'"
                />
                <span v-if="i < timeline.length - 1" class="w-px flex-1 bg-border mt-1" />
              </div>
              <div class="min-w-0 flex-1 text-sm">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium text-highlighted" :title="e.operator">{{ displayName(e.operator) }}</span>
                  <template v-if="e.from_status">
                    <UBadge :label="STATUS_META[e.from_status]?.label || e.from_status" color="neutral" variant="outline" size="sm" />
                    <UIcon name="i-lucide-arrow-right" class="size-3 text-dimmed" />
                  </template>
                  <span v-else class="text-muted text-xs">创建</span>
                  <UBadge :label="STATUS_META[e.to_status]?.label || e.to_status" :color="(STATUS_META[e.to_status]?.color as any) || 'neutral'" variant="subtle" size="sm" />
                  <span class="text-xs text-dimmed ml-auto">{{ fmtTime(e.created_at) }}</span>
                </div>
                <p v-if="e.comment" class="mt-1 text-muted whitespace-pre-wrap">{{ e.comment }}</p>
                <UBadge
                  v-if="e.artifact_type"
                  :label="`${ARTIFACT_LABELS[e.artifact_type] || e.artifact_type}：${e.artifact_ref || ''}`"
                  color="info"
                  variant="outline"
                  size="sm"
                  class="mt-1"
                />
              </div>
            </li>
          </ol>
        </UCard>
      </template>

      <!-- 流转确认弹窗 -->
      <UModal
        :open="!!pendingAction"
        :title="pendingAction?.label"
        :description="pendingAction ? `状态将变更为「${STATUS_META[pendingAction.to]?.label || pendingAction.to}」` : ''"
        @update:open="(v: boolean) => { if (!v) pendingAction = null }"
      >
        <template #body>
          <UFormField
            :label="pendingAction?.wantComment ? '意见（建议填写原因）' : '意见（可选）'"
          >
            <UTextarea v-model="comment" :rows="4" placeholder="补充说明、原因或结论…" class="w-full" autofocus />
          </UFormField>
        </template>
        <template #footer>
          <div class="flex justify-end gap-2 w-full">
            <UButton variant="ghost" color="neutral" @click="pendingAction = null">取消</UButton>
            <UButton :color="(pendingAction?.color as any) || 'primary'" :loading="transiting" @click="doTransition">
              确认{{ pendingAction?.label }}
            </UButton>
          </div>
        </template>
      </UModal>
    </div>
  </div>
</template>
