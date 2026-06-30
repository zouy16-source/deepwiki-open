<script setup lang="ts">
import { getMarkdownIt, splitMarkdownSegments, type ResolveFileHref } from '~/composables/useMarkdownRenderer'

// Ported from src/components/Markdown.tsx.
const props = defineProps<{
  content: string
  /** Turn a bare repo file path into a full source URL for citation links. */
  resolveFileHref?: ResolveFileHref
}>()

// Built once (shiki highlighter is expensive). Nuxt wraps pages in <Suspense>,
// so awaiting in setup is fine and lets markdown segments render during SSR.
const md = await getMarkdownIt()

const rendered = computed(() =>
  splitMarkdownSegments(md, props.content).map((seg) =>
    seg.type === 'mermaid'
      ? { type: 'mermaid' as const, chart: seg.chart || '' }
      : { type: 'markdown' as const, html: md.render(seg.src || '', { resolveFileHref: props.resolveFileHref }) },
  ),
)

// Copy buttons live inside v-html output, so wire them with event delegation.
const copied = ref(false)
async function onClick(e: MouseEvent) {
  const btn = (e.target as HTMLElement)?.closest?.('.copy-btn')
  if (!btn) return
  const block = btn.closest('.code-block')
  const code = block?.querySelector('.shiki')?.textContent ?? block?.querySelector('code')?.textContent ?? ''
  try {
    await navigator.clipboard.writeText(code)
    copied.value = true
    btn.classList.add('copied')
    setTimeout(() => { copied.value = false; btn.classList.remove('copied') }, 1200)
  } catch {
    // clipboard blocked (e.g. insecure context) — ignore
  }
}
</script>

<template>
  <div class="markdown-body max-w-none px-2 py-4" @click="onClick">
    <template v-for="(seg, i) in rendered" :key="i">
      <div
        v-if="seg.type === 'mermaid'"
        class="my-8 bg-gray-50 dark:bg-gray-800 rounded-md overflow-hidden shadow-sm"
      >
        <ClientOnly>
          <Mermaid :chart="seg.chart" class-name="w-full max-w-full" :zooming-enabled="false" />
          <template #fallback>
            <div class="flex justify-center items-center p-6 text-xs text-[var(--muted)]">图表加载中...</div>
          </template>
        </ClientOnly>
      </div>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div v-else v-html="seg.html" />
    </template>
  </div>
</template>
