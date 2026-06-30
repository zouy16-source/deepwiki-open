<script setup lang="ts">
// Ported from src/components/WikiDocList.tsx.
// Generated-wiki list (search + table), data from /api/wiki/projects.
// Delete confirmation uses a UModal + useToast instead of confirm()/alert().

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
        icon="i-fa6-solid-magnifying-glass"
        size="lg"
        placeholder="搜索已生成文档(名称、路径或类型),回车搜索…"
        :ui="{ root: 'w-full' }"
      />
    </form>

    <p v-if="error" class="mb-4 text-sm text-[var(--highlight)]">加载出错:{{ error }}</p>

    <div class="overflow-x-auto border border-[var(--border-color)] rounded-lg">
      <table class="min-w-full text-sm">
        <thead class="bg-[var(--background)] text-left text-[var(--muted)]">
          <tr>
            <th class="px-4 py-3 font-medium">仓库路径</th>
            <th class="px-4 py-3 font-medium">类型</th>
            <th class="px-4 py-3 font-medium">语言</th>
            <th class="px-4 py-3 font-medium">生成时间</th>
            <th class="px-4 py-3 font-medium text-right">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--border-color)]">
          <tr v-if="loading">
            <td colspan="5" class="px-4 py-8 text-center text-[var(--muted)]">加载中…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-[var(--muted)]">暂无已生成的 wiki 文档</td>
          </tr>
          <template v-else>
            <tr v-for="d in rows" :key="d.id" class="hover:bg-[var(--card-bg)] align-top">
              <td class="px-4 py-3 font-mono">
                <a :href="sourceUrl(d)" target="_blank" rel="noopener noreferrer" class="text-[var(--link-color)] hover:underline">{{ d.owner }}/{{ d.repo }}</a>
              </td>
              <td class="px-4 py-3">
                <UBadge color="primary" variant="soft" size="sm" :label="d.repo_type" />
              </td>
              <td class="px-4 py-3 text-[var(--muted)]">{{ d.language }}</td>
              <td class="px-4 py-3 text-[var(--muted)] whitespace-nowrap">{{ new Date(d.submittedAt).toLocaleString() }}</td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <UButton color="primary" variant="solid" size="xs" label="查看" @click="emit('view', d)" />
                <UButton class="ml-2" color="error" variant="outline" size="xs" label="删除" @click="askDelete(d)" />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

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
