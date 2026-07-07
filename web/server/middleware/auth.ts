// 平台 API 鉴权守卫（admin.md 6.2 决策 6：前端只面向 BFF 单入口，鉴权在 BFF 统一做）。
// 全局 server middleware 先于 routeRules 代理执行，因此 nuxt.config 里的纯代理路径同样被守住。
// INTERNAL_JWT_SECRET 为空 = 本地开发免鉴权（与 services/* 的 current_subject 约定一致）。
import { getSessionUser } from '../utils/session'
import { authEnabled } from '../utils/internalJwt'

// 会话豁免：登录/登出/会话探测；/api/auth/validate|status 是 deepwiki 旧的 wiki 访问口令接口，一并放行。
const PUBLIC_PREFIXES = ['/api/auth/']

// 需要登录态的路径：BFF 自有 handler 与 routeRules 代理的后端路径（含非 /api 前缀的代理）。
const GUARDED_PREFIXES = ['/api/', '/export/', '/local_repo/']

export default defineEventHandler((event) => {
  if (!authEnabled()) return

  const path = event.path || ''
  if (!GUARDED_PREFIXES.some(p => path.startsWith(p))) return // 页面路由由前端路由守卫处理
  if (PUBLIC_PREFIXES.some(p => path.startsWith(p))) return

  const user = getSessionUser(event)
  if (!user) {
    throw createError({ statusCode: 401, statusMessage: 'authentication required' })
  }
  event.context.user = user
})
