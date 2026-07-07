// 服务间内部 JWT（HS256）。INTERNAL_JWT_SECRET 与 services/*（identity/requirement）
// 共享（services/README.md 约定）；为空 = 本地开发免鉴权，与后端 current_subject 行为一致。
import { createHmac } from 'node:crypto'

export function internalJwtSecret(): string {
  return process.env.INTERNAL_JWT_SECRET || ''
}

export function authEnabled(): boolean {
  return !!internalJwtSecret()
}

const b64url = (input: string) => Buffer.from(input).toString('base64url')

/** BFF 每次转发时即签即用，TTL 短（默认 5 分钟）、无需刷新机制。 */
export function signInternalJwt(
  sub: string,
  claims: Record<string, unknown> = {},
  ttlSeconds = 300,
): string {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const now = Math.floor(Date.now() / 1000)
  const payload = b64url(JSON.stringify({ sub, iat: now, exp: now + ttlSeconds, ...claims }))
  const signature = createHmac('sha256', internalJwtSecret())
    .update(`${header}.${payload}`)
    .digest('base64url')
  return `${header}.${payload}.${signature}`
}
