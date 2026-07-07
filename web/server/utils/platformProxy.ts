// 平台服务代理：BFF 是前端唯一入口（admin.md 6.2 决策 6）。
// 校验会话 cookie → 以会话用户为 sub 即签短时内部 JWT → 原样转发（方法/查询/流式 body）。
// INTERNAL_JWT_SECRET 未配置（本地开发免鉴权）时不校验会话、不附 token，与后端 current_subject 行为一致。
import type { H3Event } from 'h3'

export function proxyPlatformService(event: H3Event, base: string) {
  const session = getSession(event)
  if (authEnabled() && !session) {
    throw createError({ statusCode: 401, statusMessage: 'not authenticated' })
  }
  // event.path 含查询串；BFF 与内部服务同路径约定（/api/requirements ↔ /api/requirements）
  return proxyRequest(event, `${base}${event.path}`, {
    headers: {
      ...(authEnabled()
        ? { authorization: `Bearer ${signInternalJwt(session!.username)}` }
        : {}),
      // 会话 cookie 是 BFF 私有凭证，不透传给内部服务
      cookie: '',
    },
  })
}
