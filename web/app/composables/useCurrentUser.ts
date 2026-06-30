// Current signed-in user, shared app-wide. The data is a placeholder for now —
// wire `fetchCurrentUser` to the real user API when it's available; the rest of
// the UI only depends on the `CurrentUser` shape, so the swap stays local here.
export interface CurrentUser {
  name: string
  email?: string
  /** Avatar image URL; falls back to an icon/initials when empty. */
  avatar?: string
}

export function useCurrentUser() {
  // useState keeps the user reactive, SSR-safe, and shared across components.
  const user = useState<CurrentUser>('current-user', () => ({
    name: '当前用户',
    email: 'user@example.com',
    avatar: '',
  }))

  // TODO: replace the placeholder above with the real endpoint, e.g.
  //   user.value = await $fetch<CurrentUser>('/api/user/me')
  async function fetchCurrentUser() {
    // No-op until the user API is wired up.
  }

  return { user, fetchCurrentUser }
}
