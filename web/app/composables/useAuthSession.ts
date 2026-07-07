// 登录会话（客户端视角）。服务端真相在 BFF 的 httpOnly cookie 里，
// 这里只缓存 /api/auth/me 的结果供路由守卫与 UI 使用。
export interface AuthSessionUser {
  username: string
  displayName: string
  email: string
  roles: { role: string, projectId: number | null }[]
  projectIds: number[]
}

export interface AuthSessionState {
  /** false = 后端未启用鉴权（本地开发免登录模式） */
  enabled: boolean
  user: AuthSessionUser | null
}

export function useAuthSession() {
  // null = 尚未探测过会话
  const state = useState<AuthSessionState | null>('auth-session', () => null)

  // useRequestFetch：SSR 时把浏览器 cookie 带给内部 /api/auth/me 调用
  const requestFetch = useRequestFetch()

  async function refresh(): Promise<void> {
    try {
      state.value = await requestFetch<AuthSessionState>('/api/auth/me')
    } catch {
      state.value = { enabled: true, user: null }
    }
  }

  async function login(username: string, password: string): Promise<AuthSessionUser> {
    const res = await $fetch<{ user: AuthSessionUser }>('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    })
    state.value = { enabled: true, user: res.user }
    return res.user
  }

  async function logout(): Promise<void> {
    await $fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
    state.value = { enabled: state.value?.enabled ?? true, user: null }
    await navigateTo('/login')
  }

  return { state, refresh, login, logout }
}
