<script setup lang="ts">
// Ported from src/app/page.tsx. Home dashboard: left tabs (GitLab project list /
// generated wikis) + content, with an iframe "view" for a selected wiki.

interface SelectedWiki {
  owner: string
  repo: string
  repo_type: string
  language: string
}

type View = 'projects' | 'wikis'

const view = ref<View>('projects')
const selectedWiki = ref<SelectedWiki | null>(null)

const menu: { key: View; label: string; icon: string }[] = [
  { key: 'projects', label: '项目列表', icon: 'i-fa6-solid-list' },
  { key: 'wikis', label: 'Wiki文档', icon: 'i-fa6-solid-book' },
]

function select(key: View) {
  view.value = key
  selectedWiki.value = null
}

const wikiUrl = computed(() =>
  selectedWiki.value
    ? `/${selectedWiki.value.owner}/${selectedWiki.value.repo}?type=${selectedWiki.value.repo_type}&language=${selectedWiki.value.language}`
    : '',
)
</script>

<template>
  <div class="h-full flex">
    <!-- Left sidebar -->
    <aside class="w-52 shrink-0 border-r border-[var(--border-color)] bg-[var(--card-bg)] p-3 overflow-y-auto flex flex-col">
      <nav class="flex flex-col gap-1">
        <UButton
          v-for="m in menu"
          :key="m.key"
          :icon="m.icon"
          :label="m.label"
          :color="view === m.key ? 'primary' : 'neutral'"
          :variant="view === m.key ? 'solid' : 'ghost'"
          block
          class="justify-start"
          @click="select(m.key)"
        />
      </nav>
      <div class="mt-auto pt-3 border-t border-[var(--border-color)] flex flex-col gap-1 text-xs">
        <NuxtLink to="/markdown-demo" class="text-[var(--muted)] hover:text-[var(--foreground)] px-3 py-1">渲染管线 Demo</NuxtLink>
        <NuxtLink to="/dev" class="text-[var(--muted)] hover:text-[var(--foreground)] px-3 py-1">基座自检</NuxtLink>
      </div>
    </aside>

    <!-- Right content -->
    <main class="flex-1 min-w-0 flex flex-col">
      <template v-if="view === 'wikis' && selectedWiki">
        <div class="flex items-center gap-4 px-6 py-3 border-b border-[var(--border-color)] bg-[var(--card-bg)]">
          <UButton color="neutral" variant="outline" size="sm" label="← 返回列表" @click="selectedWiki = null" />
          <span class="font-mono text-sm text-[var(--muted)] truncate">{{ selectedWiki.owner }}/{{ selectedWiki.repo }}</span>
          <a :href="wikiUrl" target="_blank" rel="noopener noreferrer" class="ml-auto text-sm text-[var(--link-color)] hover:underline whitespace-nowrap">在新标签打开 ↗</a>
        </div>
        <iframe :key="wikiUrl" :src="wikiUrl" class="flex-1 w-full border-0 bg-[var(--background)]" title="wiki" />
      </template>

      <div v-else class="flex-1 overflow-y-auto p-6">
        <h2 class="text-xl font-bold text-[var(--foreground)] mb-4">
          {{ view === 'projects' ? '项目列表(GitLab)' : 'Wiki 文档(已生成)' }}
        </h2>
        <GitlabProjectList v-if="view === 'projects'" />
        <WikiDocList v-else @view="(d) => (selectedWiki = { owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language })" />
      </div>
    </main>
  </div>
</template>
