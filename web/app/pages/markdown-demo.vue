<script setup lang="ts">
import sample from '~/assets/demo-sample.md?raw'
import type { ResolveFileHref } from '~/composables/useMarkdownRenderer'

// Resolve bare repo paths to GitHub source URLs (mirrors how the wiki page builds
// "Relevant source files" / citation links).
const resolveFileHref: ResolveFileHref = (path) =>
  `https://github.com/AsyncFuncAI/deepwiki-open/blob/main/${path.replace(/^\.?\//, '')}`
</script>

<template>
  <div class="h-full overflow-y-auto">
   <div class="max-w-4xl mx-auto p-6">
    <div class="mb-4 flex items-center gap-3 text-sm">
      <NuxtLink to="/" class="text-[var(--link-color)] hover:underline">← 返回首页</NuxtLink>
      <span class="text-[var(--muted)]">/ Phase 2 渲染管线</span>
    </div>
    <article class="card-japanese rounded-lg border border-[var(--border-color)] p-2 sm:p-4">
      <Suspense>
        <Markdown :content="sample" :resolve-file-href="resolveFileHref" />
        <template #fallback>
          <div class="p-8 text-center text-[var(--muted)] text-sm">渲染管线加载中...</div>
        </template>
      </Suspense>
    </article>
   </div>
  </div>
</template>
