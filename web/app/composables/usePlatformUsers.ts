import type { PlatformUser } from '~/types/requirement'

// 平台用户目录（identity 服务）。需求域存的是 username（跨服务不 join），
// 展示层统一映射为 displayName。useFetch 带固定 key，全站共享一次请求、组件间去重。
export function usePlatformUsers() {
  const { data: users } = useFetch<PlatformUser[]>('/api/users', {
    key: 'platform-users',
    query: { limit: 200 },
    default: () => [],
  })

  const nameMap = computed(() => {
    const m: Record<string, string> = {}
    for (const u of users.value || []) m[u.username] = u.display_name || u.username
    return m
  })

  // username -> 展示名。系统账号给友好名；查不到回退原值（不丢信息）。
  function displayName(username: string | null | undefined): string {
    if (!username) return '—'
    if (username === 'ai-analysis') return 'AI 分析'
    return nameMap.value[username] || username
  }

  return { users, displayName }
}
