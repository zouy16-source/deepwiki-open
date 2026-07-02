<script setup lang="ts">
import { diffLines } from 'diff'
import type { HistoryEntry } from '~/types/wiki'

// Per-page change timeline (who / when / what changed) with line-level diff and
// revert-to-any-version. History (incl. snapshots) is fetched on demand from the
// backend, so it never weighs down normal page loading.
const open = defineModel<boolean>({ default: false })
const props = defineProps<{
  pageId: string
  pageTitle: string
  fetchHistory: (pageId: string) => Promise<HistoryEntry[]>
  revert: (pageId: string, at: number) => Promise<boolean>
}>()
const emit = defineEmits<{ reverted: [] }>()

const entries = ref<HistoryEntry[]>([]) // chronological (oldest → newest)
const loading = ref(false)
const error = ref<string | null>(null)
const openDiffAt = ref<number | null>(null)
const revertingAt = ref<number | null>(null)

// newest-first for display, carrying the chronological index for diffing vs prev.
const rows = computed(() =>
  entries.value.map((e, i) => ({ entry: e, idx: i })).reverse(),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    entries.value = await props.fetchHistory(props.pageId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载历史失败'
  } finally {
    loading.value = false
  }
}

watch(open, (v) => {
  if (v) {
    openDiffAt.value = null
    void load()
  }
})

const ACTION_META: Record<string, { icon: string, label: string, color: string }> = {
  generated: { icon: 'i-lucide-sparkles', label: 'AI 生成', color: 'text-primary' },
  regenerated: { icon: 'i-lucide-rotate-cw', label: 'AI 重新生成', color: 'text-primary' },
  edited: { icon: 'i-lucide-pencil', label: '手动编辑', color: 'text-warning' },
  reverted: { icon: 'i-lucide-undo-2', label: '回滚', color: 'text-muted' },
}
function meta(a: string) { return ACTION_META[a] || { icon: 'i-lucide-dot', label: a, color: 'text-muted' } }
function who(e: HistoryEntry) {
  return e.source === 'ai' ? `AI · ${e.model || '模型'}` : (e.actor || '人工')
}
function fmt(ms: number) {
  try { return new Date(ms).toLocaleString() } catch { return String(ms) }
}

// Diff this entry against the previous one → "本次改动了什么".
interface DiffRow { type: 'add' | 'del' | 'ctx', text: string }
function diffRows(idx: number): DiffRow[] {
  const cur = entries.value[idx]?.content ?? ''
  const prev = idx > 0 ? (entries.value[idx - 1]?.content ?? '') : ''
  const out: DiffRow[] = []
  for (const p of diffLines(prev, cur)) {
    const lines = p.value.replace(/\n$/, '').split('\n')
    if (!p.added && !p.removed) {
      if (lines.length > 4) out.push({ type: 'ctx', text: `… ${lines.length} 行未改动 …` })
      else for (const l of lines) out.push({ type: 'ctx', text: l })
    } else {
      const t: 'add' | 'del' = p.added ? 'add' : 'del'
      for (const l of lines) out.push({ type: t, text: l })
    }
  }
  return out
}
function toggleDiff(at: number) { openDiffAt.value = openDiffAt.value === at ? null : at }

async function doRevert(at: number) {
  revertingAt.value = at
  try {
    if (await props.revert(props.pageId, at)) {
      emit('reverted')
      await load() // a new "回滚" entry was appended
    }
  } finally {
    revertingAt.value = null
  }
}
</script>

<template>
  <USlideover v-model:open="open" :title="`修改历史 · ${pageTitle}`" :ui="{ content: 'max-w-2xl w-full' }">
    <template #body>
      <div v-if="loading" class="p-6 text-center text-sm text-muted">加载历史中…</div>
      <p v-else-if="error" class="p-4 text-sm text-error">{{ error }}</p>
      <div v-else-if="!entries.length" class="p-6 text-center text-sm text-muted">暂无历史记录</div>

      <ol v-else class="relative border-l border-default ml-3 pl-5 space-y-5 py-2">
        <li v-for="{ entry, idx } in rows" :key="entry.at" class="relative">
          <span class="absolute -left-[27px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-elevated border border-default">
            <UIcon :name="meta(entry.action).icon" class="h-3 w-3" :class="meta(entry.action).color" />
          </span>

          <div class="flex items-center gap-2 flex-wrap text-sm">
            <UBadge :color="entry.source === 'human' ? 'warning' : 'primary'" variant="soft" size="xs" :label="meta(entry.action).label" />
            <span class="text-default font-medium">{{ who(entry) }}</span>
            <span class="text-xs text-muted">{{ fmt(entry.at) }}</span>
          </div>
          <p v-if="entry.summary" class="text-xs text-muted mt-1 break-words">{{ entry.summary }}</p>
          <div class="flex items-center gap-1.5 mt-2">
            <UButton size="xs" variant="ghost" color="neutral" :icon="openDiffAt === entry.at ? 'i-lucide-chevron-down' : 'i-lucide-git-compare'" :label="openDiffAt === entry.at ? '收起差异' : '本次改动'" @click="toggleDiff(entry.at)" />
            <UButton size="xs" variant="ghost" color="primary" icon="i-lucide-history" label="回滚到此版本" :loading="revertingAt === entry.at" @click="doRevert(entry.at)" />
            <span class="text-xs text-muted ml-auto">{{ entry.size }} 字</span>
          </div>

          <div v-if="openDiffAt === entry.at" class="mt-2 border border-default rounded-md overflow-hidden font-mono text-xs leading-relaxed max-h-72 overflow-y-auto">
            <div
              v-for="(r, i) in diffRows(idx)" :key="i"
              class="whitespace-pre-wrap break-words px-2 py-0.5"
              :class="{
                'bg-success/10 text-success': r.type === 'add',
                'bg-error/10 text-error': r.type === 'del',
                'text-muted': r.type === 'ctx',
              }"
            >{{ r.type === 'add' ? '+ ' : r.type === 'del' ? '- ' : '  ' }}{{ r.text }}</div>
          </div>
        </li>
      </ol>
    </template>
  </USlideover>
</template>
