// Current signed-in user, shared app-wide. Reads from the auth session
// (populated by the global auth middleware via /api/auth/me); the UI only
// depends on the `CurrentUser` shape, so consumers stay unchanged.
export interface CurrentUser {
  name: string
  email?: string
  /** Avatar image URL; falls back to an icon/initials when empty. */
  avatar?: string
}

export function useCurrentUser() {
  const { state, refresh } = useAuthSession()

  const user = computed<CurrentUser>(() => {
    const u = state.value?.user
    if (u) return { name: u.displayName || u.username, email: u.email, avatar: '' }
    // 本地免鉴权模式（enabled=false）或会话未就绪时的占位
    return { name: '开发模式', email: '', avatar: '' }
  })

  async function fetchCurrentUser() {
    await refresh()
  }

  return { user, fetchCurrentUser }
}
