<script setup lang="ts">
// Dashboard shell for the home section (project list / wiki docs). The sidebar
// menu items are real routes (URL changes on click); the layout stays mounted
// across them, only the panel body (<slot/>) swaps.
import type { DropdownMenuItem, NavigationMenuItem } from '@nuxt/ui'

const { t } = useI18n()
const route = useRoute()

// Sidebar footer user. Placeholder data for now — see useCurrentUser.
const { user } = useCurrentUser()

// Actions for the footer user dropdown. Handlers are stubs until the user/auth
// API exists — fill in `onSelect` (or swap to `to:` routes) when it's wired up.
const userMenuItems = computed<DropdownMenuItem[][]>(() => [
  [{ label: user.value.name, avatar: { src: user.value.avatar || undefined, alt: user.value.name }, type: 'label' }],
  [
    { label: '个人资料', icon: 'i-lucide-user' },
    { label: '设置', icon: 'i-lucide-settings' },
  ],
  [{ label: '退出登录', icon: 'i-lucide-log-out', color: 'error' }],
])

// A wiki detail route (/{owner}/{repo}) renders inside this layout too.
const isDetail = computed(() => !!route.params.owner && !!route.params.repo)

const navItems = computed<NavigationMenuItem[][]>(() => [[
  { label: '项目列表', icon: 'i-lucide-folder-git-2', to: '/', active: route.path === '/' },
  { label: 'Wiki 文档', icon: 'i-lucide-book-marked', to: '/wikis', active: route.path === '/wikis' || isDetail.value },
]])

const devItems: NavigationMenuItem[][] = [[
  { label: '渲染管线 Demo', icon: 'i-lucide-sparkles', to: '/markdown-demo' },
  { label: '基座自检', icon: 'i-lucide-wrench', to: '/dev' },
]]

const navTitle = computed(() => {
  if (isDetail.value) return `${route.params.owner}/${route.params.repo}`
  return route.path === '/wikis' ? 'Wiki 文档(已生成)' : '项目列表(GitLab)'
})
const navBadge = computed(() => (route.path === '/wikis' ? '已生成' : isDetail.value ? '' : 'GitLab'))
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
      :ui="{ root: 'dash-sidebar', footer: 'border-t border-default' }"
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
        <UDropdownMenu
          :items="userMenuItems"
          :content="{ side: 'top', align: collapsed ? 'center' : 'start' }"
          :ui="{ content: collapsed ? undefined : 'w-(--reka-dropdown-menu-trigger-width)' }"
          class="w-full"
        >
          <UButton
            color="neutral"
            variant="ghost"
            class="w-full gap-2.5"
            :class="collapsed ? 'justify-center' : 'justify-start'"
            :square="collapsed"
          >
            <UAvatar
              :src="user.avatar || undefined"
              :alt="user.name"
              icon="i-lucide-user"
              size="md"
              class="shrink-0"
            />
            <div v-if="!collapsed" class="min-w-0 text-left">
              <p class="text-sm font-medium text-highlighted truncate">{{ user.name }}</p>
              <p v-if="user.email" class="text-xs text-muted truncate">{{ user.email }}</p>
            </div>
            <UIcon v-if="!collapsed" name="i-lucide-chevrons-up-down" class="shrink-0 ml-auto size-4 text-dimmed" />
          </UButton>
        </UDropdownMenu>
      </template>

      <!-- <template #footer="{ collapsed }">
        <UNavigationMenu :collapsed="collapsed" :items="devItems" orientation="vertical" class="w-full" />
      </template> -->
    </UDashboardSidebar>

    <UDashboardPanel id="home-content" :ui="{ body: 'p-0 sm:p-0 overflow-y-hidden' }">
      <template #header>
        <UDashboardNavbar :title="navTitle" :toggle="true">
          <template #leading>
            <UDashboardSidebarCollapse />
          </template>
          <template #trailing>
            <UBadge v-if="navBadge" :label="navBadge" color="primary" variant="subtle" size="sm" />
          </template>
          <template #right>
            <!-- <LocaleSwitcher class="hidden sm:flex" /> -->
            <ThemeToggle />
          </template>
        </UDashboardNavbar>
      </template>

      <template #body>
        <slot />
      </template>
    </UDashboardPanel>
  </UDashboardGroup>
</template>
