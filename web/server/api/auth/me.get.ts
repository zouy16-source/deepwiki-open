// 会话探测：前端路由守卫据此决定是否跳登录页。
// enabled=false（INTERNAL_JWT_SECRET 未配置）= 本地开发免鉴权模式，前端不强制登录。
export default defineEventHandler((event) => {
  return {
    enabled: authEnabled(),
    user: getSession(event),
  }
})
