<script setup lang="ts">
// Home dashboard, built with Nuxt UI's Dashboard components (sidebar collapses to
// icons on desktop and becomes a slideover on mobile — responsive out of the box).
import type { NavigationMenuItem } from '@nuxt/ui'

definePageMeta({ layout: false })

const { t } = useI18n()

interface SelectedWiki { owner: string; repo: string; repo_type: string; language: string }
type View = 'projects' | 'wikis'

const view = ref<View>('projects')
const selectedWiki = ref<SelectedWiki | null>(null)

function select(v: View) {
  view.value = v
  selectedWiki.value = null
}

const navItems = computed<NavigationMenuItem[][]>(() => [[
  {
    label: '项目列表',
    icon: 'i-lucide-folder-git-2',
    active: view.value === 'projects',
    onSelect: () => select('projects'),
  },
  {
    label: 'Wiki 文档',
    icon: 'i-lucide-book-marked',
    active: view.value === 'wikis',
    onSelect: () => select('wikis'),
  },
]])

const devItems: NavigationMenuItem[][] = [[
  { label: '渲染管线 Demo', icon: 'i-lucide-sparkles', to: '/markdown-demo' },
  { label: '基座自检', icon: 'i-lucide-wrench', to: '/dev' },
]]

const wikiUrl = computed(() =>
  selectedWiki.value
    ? `/${selectedWiki.value.owner}/${selectedWiki.value.repo}?type=${selectedWiki.value.repo_type}&language=${selectedWiki.value.language}`
    : '',
)

const navTitle = computed(() =>
  selectedWiki.value
    ? `${selectedWiki.value.owner}/${selectedWiki.value.repo}`
    : view.value === 'projects'
      ? '项目列表(GitLab)'
      : 'Wiki 文档(已生成)',
)
</script>

<template>
  <UDashboardGroup>
    <UDashboardSidebar
      id="home"
      collapsible
      resizable
      :default-size="18"
      :min-size="14"
      :max-size="26"
      :ui="{ footer: 'border-t border-default' }"
    >
      <template #header="{ collapsed }">
        <div class="flex items-center gap-2 min-w-0">
          <span class="shrink-0 inline-flex items-center justify-center size-8 rounded-lg bg-primary text-inverted">
            <UIcon name="i-lucide-book-open-text" class="size-5" />
          </span>
          <span v-if="!collapsed" class="font-bold text-primary truncate">{{ t('common.appName') }}</span>
        </div>
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu :collapsed="collapsed" :items="navItems" orientation="vertical" />
      </template>

      <template #footer="{ collapsed }">
        <UNavigationMenu :collapsed="collapsed" :items="devItems" orientation="vertical" class="w-full" />
      </template>
    </UDashboardSidebar>

    <UDashboardPanel id="home-content" :ui="{ body: 'p-0 sm:p-0' }">
      <template #header>
        <UDashboardNavbar :title="navTitle" :toggle="true">
          <template #leading>
            <UDashboardSidebarCollapse />
          </template>
          <template #trailing>
            <UBadge
              v-if="!selectedWiki"
              :label="view === 'projects' ? 'GitLab' : '已生成'"
              color="primary"
              variant="subtle"
              size="sm"
            />
          </template>
          <template #right>
            <LocaleSwitcher class="hidden sm:flex" />
            <ThemeToggle />
          </template>
        </UDashboardNavbar>
      </template>

      <template #body>
        <!-- Wiki iframe view (full-bleed) -->
        <div v-if="view === 'wikis' && selectedWiki" class="flex flex-col h-full">
          <div class="flex items-center gap-3 px-4 sm:px-6 py-2 border-b border-default bg-elevated/50">
            <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-arrow-left" label="返回列表" @click="selectedWiki = null" />
            <span class="font-mono text-sm text-muted truncate">{{ selectedWiki.owner }}/{{ selectedWiki.repo }}</span>
            <UButton :to="wikiUrl" target="_blank" color="neutral" variant="ghost" size="sm" icon="i-lucide-external-link" label="新标签打开" class="ml-auto" />
          </div>
          <iframe :key="wikiUrl" :src="wikiUrl" class="flex-1 w-full border-0 bg-default" title="wiki" />
        </div>

        <!-- Lists -->
        <div v-else class="p-4 sm:p-6">
          <GitlabProjectList v-if="view === 'projects'" />
          <WikiDocList
            v-else
            @view="(d) => (selectedWiki = { owner: d.owner, repo: d.repo, repo_type: d.repo_type, language: d.language })"
          />
        </div>
      </template>
    </UDashboardPanel>
  </UDashboardGroup>
</template>
