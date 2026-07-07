// 平台登录（FR-ADM-01）。LDAP 是唯一认证源（已决策不做本地回退）：
// identity 服务做 search-then-bind，这里只负责限流、换会话 cookie。
// 对客户端只区分 401（凭据错误）/ 429（限流）/ 503（目录或 identity 不可用）。
import type { SessionUser } from '../../utils/session'

interface VerifyResponse {
  user: { username: string, display_name: string, email: string }
  roles: { role: string, project_id: number | null }[]
  project_ids: number[]
}

// 简易登录限流：IP 维度 1 分钟 5 次。进程内 Map，多实例部署时换 Redis。
const attempts = new Map<string, number[]>()
const WINDOW_MS = 60_000
const MAX_ATTEMPTS = 5

export default defineEventHandler(async (event) => {
  const body = await readBody(event).catch(() => null)
  const username = body?.username
  const password = body?.password
  if (typeof username !== 'string' || typeof password !== 'string' || !username || !password) {
    throw createError({ statusCode: 400, statusMessage: 'username and password required' })
  }

  const ip = getRequestIP(event, { xForwardedFor: true }) || 'unknown'
  const now = Date.now()
  const recent = (attempts.get(ip) || []).filter(t => now - t < WINDOW_MS)
  if (recent.length >= MAX_ATTEMPTS) {
    throw createError({ statusCode: 429, statusMessage: 'too many login attempts' })
  }
  recent.push(now)
  attempts.set(ip, recent)

  let res: Response
  try {
    res = await fetch(`${identityBaseUrl()}/internal/auth/verify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authEnabled() ? { Authorization: `Bearer ${signInternalJwt('svc:bff')}` } : {}),
      },
      body: JSON.stringify({ username, password }),
    })
  } catch {
    throw createError({ statusCode: 503, statusMessage: 'authentication service unavailable' })
  }

  if (res.status === 401 || res.status === 422) {
    throw createError({ statusCode: 401, statusMessage: 'invalid username or password' })
  }
  if (!res.ok) {
    throw createError({ statusCode: 503, statusMessage: 'authentication service unavailable' })
  }

  const data = await res.json() as VerifyResponse
  const user: SessionUser = {
    username: data.user.username,
    displayName: data.user.display_name || data.user.username,
    email: data.user.email || '',
    roles: (data.roles || []).map(r => ({ role: r.role, projectId: r.project_id })),
    projectIds: data.project_ids || [],
  }
  setSession(event, user)
  return { user }
})
