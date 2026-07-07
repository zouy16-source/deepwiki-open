// 全局登录守卫：未登录访问任意页面 → 跳 /login（带回跳地址）。
// 后端未启用鉴权（INTERNAL_JWT_SECRET 为空，本地开发）时 me 返回 enabled=false，直接放行。
export default defineNuxtRouteMiddleware(async (to) => {
  if (to.path === '/login') return

  const { state, refresh } = useAuthSession()
  if (state.value === null) await refresh()

  if (state.value?.enabled && !state.value.user) {
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } }, { replace: true })
  }
})
