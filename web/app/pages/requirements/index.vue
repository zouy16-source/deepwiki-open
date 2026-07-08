<script setup lang="ts">
// 需求列表（FR-REQ-01/02 入口）：筛选 + 分页，行点击进详情。UTable 承载。
import type { TableColumn, TableRow } from '@nuxt/ui'
import type { Project, Requirement } from '~/types/requirement'

definePageMeta({ layout: 'home' })

const PAGE_SIZE = 20
const status = ref('all')
const projectId = ref<'all' | number>('all')
const offset = ref(0)

const statusItems = [
  { label: '全部状态', value: 'all' },
  ...Object.entries(STATUS_META).map(([value, m]) => ({ label: m.label, value })),
]

const { data: projects } = useFetch<Project[]>('/api/projects', { default: () => [] })
const projectItems = computed(() => [
  { label: '全部项目', value: 'all' as const },
  ...(projects.value || []).map(p => ({ label: p.name, value: p.id })),
])
const projectName = (id: number) => projects.value?.find(p => p.id === id)?.name || `#${id}`

const { displayName } = usePlatformUsers()

watch([status, projectId], () => { offset.value = 0 })

const query = computed(() => ({
  limit: PAGE_SIZE,
  offset: offset.value,
  ...(status.value !== 'all' ? { status: status.value } : {}),
  ...(projectId.value !== 'all' ? { project_id: projectId.value } : {}),
}))
const { data: reqs, pending, error } = useFetch<Requirement[]>('/api/requirements', {
  query,
  default: () => [],
})

// 列定义：宽度/响应式隐藏/单行截断经 meta.class 下发到 th、td；单元格内容用 #<col>-cell slots 渲染。
const columns: TableColumn<Requirement>[] = [
  { accessorKey: 'id', header: 'ID', meta: { class: { th: 'w-16', td: 'w-16 text-muted truncate' } } },
  { accessorKey: 'title', header: '标题' },
  { accessorKey: 'status', header: '状态', meta: { class: { th: 'w-24', td: 'w-24' } } },
  { accessorKey: 'priority', header: '优先级', meta: { class: { th: 'w-20', td: 'w-20' } } },
  { accessorKey: 'project_id', header: '项目', meta: { class: { th: 'w-36 hidden md:table-cell', td: 'w-36 hidden md:table-cell text-muted truncate' } } },
  { accessorKey: 'expected_online_date', header: '期望上线', meta: { class: { th: 'w-28 hidden lg:table-cell', td: 'w-28 hidden lg:table-cell text-muted truncate' } } },
  { accessorKey: 'creator', header: '创建人', meta: { class: { th: 'w-24 hidden lg:table-cell', td: 'w-24 hidden lg:table-cell text-muted truncate' } } },
  { accessorKey: 'updated_at', header: '更新时间', meta: { class: { th: 'w-40 hidden sm:table-cell', td: 'w-40 hidden sm:table-cell text-muted truncate' } } },
]

function onSelect(_e: Event, row: TableRow<Requirement>) {
  navigateTo(`/requirements/${row.original.id}`)
}
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-full mx-auto p-4 sm:p-6 space-y-4">
      <div class="flex flex-wrap items-center gap-3">
        <USelect v-model="status" :items="statusItems" class="w-36" />
        <USelect v-model="projectId" :items="projectItems" class="w-48" />
        <span v-if="pending" class="text-xs text-muted">加载中…</span>
        <UButton icon="i-lucide-messages-square" class="ml-auto" to="/requirements/chat">
          对话创建需求
        </UButton>
        <UButton icon="i-lucide-plus" variant="soft" to="/requirements/new">
          新建需求
        </UButton>
      </div>

      <UAlert
        v-if="error"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        title="需求列表加载失败"
        :description="error.statusMessage || String(error)"
      />

      <div v-else class="reqs-table border border-default rounded-lg overflow-hidden">
        <UTable
          :data="reqs"
          :columns="columns"
          :loading="pending"
          :ui="{ tr: 'cursor-pointer', td: 'py-2.5', th: 'py-2' }"
          @select="onSelect"
        >
          <template #id-cell="{ row }">
            #{{ row.original.id }}
          </template>
          <template #title-cell="{ row }">
            <div class="flex items-center gap-2 min-w-0">
              <UBadge
                :label="TYPE_LABELS[row.original.req_type]"
                :color="row.original.req_type === 'business' ? 'primary' : 'neutral'"
                variant="outline"
                size="sm"
                class="shrink-0"
              />
              <span class="truncate font-medium text-highlighted" :title="row.original.title">{{ row.original.title }}</span>
              <UIcon v-if="row.original.parent_id" name="i-lucide-corner-down-right" class="size-3.5 text-dimmed shrink-0" title="子需求" />
            </div>
          </template>
          <template #status-cell="{ row }">
            <UBadge :label="STATUS_META[row.original.status]?.label || row.original.status" :color="(STATUS_META[row.original.status]?.color as any) || 'neutral'" variant="subtle" size="sm" />
          </template>
          <template #priority-cell="{ row }">
            <UBadge :label="row.original.priority" :color="(PRIORITY_COLORS[row.original.priority] as any) || 'neutral'" variant="outline" size="sm" />
          </template>
          <template #project_id-cell="{ row }">
            <span :title="projectName(row.original.project_id)">{{ projectName(row.original.project_id) }}</span>
          </template>
          <template #expected_online_date-cell="{ row }">
            {{ row.original.expected_online_date || '—' }}
          </template>
          <template #creator-cell="{ row }">
            <span :title="row.original.creator">{{ displayName(row.original.creator) }}</span>
          </template>
          <template #updated_at-cell="{ row }">
            {{ fmtTime(row.original.updated_at) }}
          </template>

          <template #empty>
            <div class="py-16 text-center text-muted">
              <UIcon name="i-lucide-clipboard-list" class="size-10 mx-auto mb-3 opacity-50" />
              <p>暂无需求{{ status !== 'all' || projectId !== 'all' ? '（当前筛选条件下）' : '' }}</p>
              <UButton v-if="status === 'all' && projectId === 'all'" variant="link" to="/requirements/new">
                提交第一条需求
              </UButton>
            </div>
          </template>
        </UTable>
      </div>

      <div v-if="reqs?.length || offset > 0" class="flex items-center justify-end gap-2">
        <UButton
          variant="ghost"
          color="neutral"
          size="sm"
          icon="i-lucide-chevron-left"
          :disabled="offset === 0"
          @click="offset = Math.max(0, offset - PAGE_SIZE)"
        >
          上一页
        </UButton>
        <UButton
          variant="ghost"
          color="neutral"
          size="sm"
          trailing-icon="i-lucide-chevron-right"
          :disabled="(reqs?.length || 0) < PAGE_SIZE"
          @click="offset = offset + PAGE_SIZE"
        >
          下一页
        </UButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 固定表格布局：让列宽尊重 meta 设定的 w-*，标题列超长才截断出省略号（truncate 才生效） */
.reqs-table :deep(table) {
  table-layout: fixed;
  width: 100%;
}
</style>
