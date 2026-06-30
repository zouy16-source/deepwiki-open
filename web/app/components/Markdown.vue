<script setup lang="ts">
// Renders LLM-generated markdown via @nuxtjs/mdc → Nuxt UI Prose components
// (ProsePre code blocks with Shiki, ProseTable, KaTeX math). Two extras:
//  • ```mermaid fences are split out and rendered with <Mermaid> (diagram), and
//  • "Relevant source files" / inline-citation links are resolved to source URLs
//    by rewriting the markdown before MDC parses it (keeps Nuxt UI's ProseA).
const props = defineProps<{
  content: string
  resolveFileHref?: (path: string) => string
}>()

// --- citation link resolution (ported from the old markdown-it renderer) ---
function isBareFilePath(href: string): boolean {
  if (!href) return false
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return false // has a scheme
  if (/^[/#?]/.test(href)) return false // absolute / anchor / query
  return /\.[a-z0-9]{1,8}(#.*)?$/i.test(href) // ends in a file extension
}
function citationHref(text: string, resolve: (p: string) => string): string | null {
  const t = text.trim()
  const m = t.match(/^(.+?\.[a-z0-9]{1,8}):(\d+)(?:-(\d+))?$/i)
  if (m) {
    const base = resolve(m[1])
    if (!base || base === m[1]) return null
    const anchor = base.includes('/-/blob/')
      ? `#L${m[2]}${m[3] ? `-${m[3]}` : ''}`
      : `#L${m[2]}${m[3] ? `-L${m[3]}` : ''}`
    return base + anchor
  }
  if (isBareFilePath(t)) {
    const base = resolve(t)
    return base && base !== t ? base : null
  }
  return null
}
function resolveCitations(md: string): string {
  const resolve = props.resolveFileHref
  if (!resolve) return md
  // [text](href) — skip images (preceded by '!').
  return md.replace(/(?<!!)\[([^\]]*)\]\(([^)]*)\)/g, (full, text: string, href: string) => {
    let finalHref = href
    if (href && isBareFilePath(href)) finalHref = resolve(href)
    else if (!href) finalHref = citationHref(text, resolve) || ''
    return finalHref && finalHref !== href ? `[${text}](${finalHref})` : full
  })
}

interface Segment { type: 'markdown' | 'mermaid'; value: string }

const segments = computed<Segment[]>(() => {
  const content = props.content || ''
  const out: Segment[] = []
  const re = /```mermaid[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) {
      const md = content.slice(last, m.index)
      if (md.trim()) out.push({ type: 'markdown', value: resolveCitations(md) })
    }
    out.push({ type: 'mermaid', value: m[1] })
    last = re.lastIndex
  }
  if (last < content.length) {
    const md = content.slice(last)
    if (md.trim()) out.push({ type: 'markdown', value: resolveCitations(md) })
  }
  if (!out.length) out.push({ type: 'markdown', value: resolveCitations(content) })
  return out
})
</script>

<template>
  <div class="markdown-body max-w-none">
    <template v-for="(seg, i) in segments" :key="i">
      <div v-if="seg.type === 'mermaid'" class="my-6 bg-muted/40 rounded-md overflow-hidden">
        <ClientOnly>
          <Mermaid :chart="seg.value" class-name="w-full max-w-full" :zooming-enabled="false" />
          <template #fallback>
            <div class="flex justify-center items-center p-6 text-xs text-muted">图表加载中...</div>
          </template>
        </ClientOnly>
      </div>
      <MDC v-else :value="seg.value" />
    </template>
  </div>
</template>
