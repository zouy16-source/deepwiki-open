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
  // LLM often wraps citations in inline-code backticks (copied from the prompt's
  // format examples) — "Sources: [...]()" or a bare "[file:lines]()" — so MDC renders
  // them as literal code instead of links. Strip backticks ONLY around spans whose
  // ENTIRE content is citation(s): an optional "Sources:" prefix + one or more
  // [text]() links + separators/punctuation. This deliberately does NOT match a code
  // span's closing backtick paired with the next span's opening backtick around inline
  // prose (which would merge two legit code spans and swallow a citation).
  const unwrapped = md.replace(
    /`(\s*(?:sources?\s*[:：])?\s*(?:\[[^\]]+\]\(\)[\s,，、]*)+[.。]?\s*)`/gi,
    '$1',
  )
  // [text](href) — skip images (preceded by '!').
  return unwrapped.replace(/(?<!!)\[([^\]]*)\]\(([^)]*)\)/g, (full, text: string, href: string) => {
    let finalHref = href
    if (href && isBareFilePath(href)) finalHref = resolve(href)
    else if (!href) finalHref = citationHref(text, resolve) || ''
    return finalHref && finalHref !== href ? `[${text}](${finalHref})` : full
  })
}

// Older caches were generated with an English "<details>" template and the LLM
// sometimes copied a prompt instruction into it. Localize the header/intro and
// drop the leaked instruction so existing pages read cleanly (new pages are
// already generated localized).
function normalizeSourceBlock(md: string): string {
  return md
    .replace(/<summary>\s*Relevant source files\s*<\/summary>/gi, '<summary>相关源文件</summary>')
    .replace(
      /The following files were used as context for generating this wiki page:/gi,
      '以下文件用于生成本页面时作为上下文参考:',
    )
    .replace(
      /Remember, do not provide any acknowledgements, disclaimers, apologies, or any other preface before the `?<details>`? block\. JUST START with the `?<details>`? block\.\s*/gi,
      '',
    )
}

interface Segment { type: 'markdown' | 'mermaid'; value: string }

const segments = computed<Segment[]>(() => {
  const content = normalizeSourceBlock(props.content || '')
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
