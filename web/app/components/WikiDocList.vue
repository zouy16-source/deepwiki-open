<script setup lang="ts">
// Generated-wiki list using Nuxt UI UTable. Data from /api/wiki/projects.
// Delete confirmation uses a UModal + useToast.
import type { TableColumn } from '@nuxt/ui'

interface WikiDoc {
  id: string
  owner: string
  repo: string
  name: string
  repo_type: string
  submittedAt: number
  language: string
}

const emit = defineEmits<{ view: [doc: WikiDoc] }>()

const config = useRuntimeConfig()
const gitlabBase = config.public.gitlabBase || 'https://gitlab.com'
const toast = useToast()

function sourceUrl(d: WikiDoc): string {
  const t = (d.repo_type || '').toLowerCase()
  if (t.includes('github')) return `https://github.com/${d.owner}/${d.repo}`
  if (t.includes('bitbucket')) return `https://bitbucket.org/${d.owner}/${d.repo}`
  return `${gitlabBase}/${d.owner}/${d.repo}`
}

const docs = ref<WikiDoc[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const searchInput = ref('')
const query = ref('')

async function fetchDocs() {
  loading.value = true
  error.value = null
  try {
    const data = await $fetch<WikiDoc[] | { error?: string }>('/api/wiki/projects')
    if (!Array.isArray(data)) throw new Error((data as { error?: string }).error || '加载失败')
    docs.value = data
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
    docs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchDocs)

function submitSearch() {
  query.value = searchInput.value.trim().toLowerCase()
}

const rows = computed(() => {
  const q = query.value
  if (!q) return docs.value
  return docs.value.filter(
    (d) =>
      d.name.toLowerCase().includes(q) ||
      d.owner.toLowerCase().includes(q) ||
      d.repo.toLowerCase().includes(q) ||
      d.repo_type.toLowerCase().includes(q),
  )
})

const columns: TableColumn<WikiDoc>[] = [
  { accessorKey: 'path', header: '仓库路径' },
  { accessorKey: 'type', header: '类型' },
  { accessorKey: 'language', header: '语言' },
  { accessorKey: 'time', header: '生成时间' },
  { id: 'actions', header: '操作', meta: { class: { th: 'text-right', td: 'text-right' } } },
]

// Delete confirmation modal state.
const confirmOpen = ref(false)
const pending = ref<WikiDoc | null>(null)
const deleting = ref(false)

function askDelete(d: WikiDoc) {
  pending.value = d
  confirmOpen.value = true
}

async function confirmDelete() {
  const d = pending.value
  if (!d) return
  deleting.value = true
  try {
    await $fetch('/api/wiki/projects', {
      method: 'DELETE',
      body: { owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language },
    })
    docs.value = docs.value.filter((x) => x.id !== d.id)
    toast.add({ title: '已删除', description: d.name, color: 'success' })
    confirmOpen.value = false
  } catch (e) {
    const msg = e instanceof Error ? e.message : '未知错误'
    toast.add({ title: '删除失败', description: msg, color: 'error' })
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div>
    <form class="mb-4" @submit.prevent="submitSearch">
      <UInput
        v-model="searchInput"
        icon="i-lucide-search"
        size="lg"
        placeholder="搜索已生成文档(名称、路径或类型),回车搜索…"
        class="w-full"
      />
    </form>

    <p v-if="error" class="mb-4 text-sm text-error">加载出错:{{ error }}</p>

    <UTable
      :data="rows"
      :columns="columns"
      :loading="loading"
      :empty="'暂无已生成的 wiki 文档'"
      class="border border-default rounded-lg"
    >
      <template #path-cell="{ row }">
        <a :href="sourceUrl(row.original)" target="_blank" rel="noopener noreferrer" class="font-mono text-primary hover:underline">
          {{ row.original.owner }}/{{ row.original.repo }}
        </a>
      </template>

      <template #type-cell="{ row }">
        <UBadge color="primary" variant="soft" size="sm" :label="row.original.repo_type" />
      </template>

      <template #language-cell="{ row }">
        <span class="text-muted">{{ row.original.language }}</span>
      </template>

      <template #time-cell="{ row }">
        <span class="text-muted whitespace-nowrap">{{ new Date(row.original.submittedAt).toLocaleString() }}</span>
      </template>

      <template #actions-cell="{ row }">
        <div class="flex justify-end gap-2">
          <UButton color="primary" variant="solid" size="xs" icon="i-lucide-eye" label="查看" @click="emit('view', row.original)" />
          <UButton color="error" variant="outline" size="xs" icon="i-lucide-trash-2" label="删除" @click="askDelete(row.original)" />
        </div>
      </template>
    </UTable>

    <UModal v-model:open="confirmOpen" title="确认删除" :description="pending ? `确定删除「${pending.name}」的 wiki 吗？此操作不可撤销。` : ''">
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="取消" :disabled="deleting" @click="confirmOpen = false" />
          <UButton color="error" variant="solid" label="删除" :loading="deleting" @click="confirmDelete" />
        </div>
      </template>
    </UModal>
  </div>
</template>
