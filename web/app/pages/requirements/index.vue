<script setup lang="ts">
// 需求列表（FR-REQ-01/02 入口）：筛选 + 分页，行点击进详情。
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

      <div v-else-if="!pending && !reqs?.length" class="py-20 text-center text-muted">
        <UIcon name="i-lucide-clipboard-list" class="size-10 mx-auto mb-3 opacity-50" />
        <p>暂无需求{{ status !== 'all' || projectId !== 'all' ? '（当前筛选条件下）' : '' }}</p>
        <UButton v-if="status === 'all' && projectId === 'all'" variant="link" to="/requirements/new">
          提交第一条需求
        </UButton>
      </div>

      <div v-else class="border border-default rounded-lg overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-muted border-b border-default bg-elevated/50">
              <th class="px-3 py-2 font-medium w-16">ID</th>
              <th class="px-3 py-2 font-medium">标题</th>
              <th class="px-3 py-2 font-medium w-24">状态</th>
              <th class="px-3 py-2 font-medium w-16">优先级</th>
              <th class="px-3 py-2 font-medium w-36 hidden md:table-cell">项目</th>
              <th class="px-3 py-2 font-medium w-28 hidden lg:table-cell">期望上线</th>
              <th class="px-3 py-2 font-medium w-24 hidden lg:table-cell">创建人</th>
              <th class="px-3 py-2 font-medium w-36 hidden sm:table-cell">更新时间</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-default">
            <tr
              v-for="r in reqs"
              :key="r.id"
              class="cursor-pointer hover:bg-elevated/50 transition-colors"
              @click="navigateTo(`/requirements/${r.id}`)"
            >
              <td class="px-3 py-2.5 text-muted">#{{ r.id }}</td>
              <td class="px-3 py-2.5">
                <div class="flex items-center gap-2 min-w-0">
                  <UBadge
                    :label="TYPE_LABELS[r.req_type]"
                    :color="r.req_type === 'business' ? 'primary' : 'neutral'"
                    variant="outline"
                    size="sm"
                    class="shrink-0"
                  />
                  <span class="truncate font-medium text-highlighted">{{ r.title }}</span>
                  <UIcon v-if="r.parent_id" name="i-lucide-corner-down-right" class="size-3.5 text-dimmed shrink-0" title="子需求" />
                </div>
              </td>
              <td class="px-3 py-2.5">
                <UBadge :label="STATUS_META[r.status]?.label || r.status" :color="(STATUS_META[r.status]?.color as any) || 'neutral'" variant="subtle" size="sm" />
              </td>
              <td class="px-3 py-2.5">
                <UBadge :label="r.priority" :color="(PRIORITY_COLORS[r.priority] as any) || 'neutral'" variant="outline" size="sm" />
              </td>
              <td class="px-3 py-2.5 text-muted hidden md:table-cell truncate">{{ projectName(r.project_id) }}</td>
              <td class="px-3 py-2.5 text-muted hidden lg:table-cell">{{ r.expected_online_date || '—' }}</td>
              <td class="px-3 py-2.5 text-muted hidden lg:table-cell truncate">{{ r.creator }}</td>
              <td class="px-3 py-2.5 text-muted hidden sm:table-cell">{{ fmtTime(r.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
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
