// 登录会话：HMAC-SHA256 签名的 httpOnly cookie（admin.md 6.2 决策 6：鉴权在 BFF 统一做）。
// payload 只有用户名/角色等非机密信息，防篡改即可，不需要加密。
// 签名密钥从 INTERNAL_JWT_SECRET 派生——BFF 与后端服务共用一个根密钥，少配一项。
import { createHmac, timingSafeEqual } from 'node:crypto'
import type { H3Event } from 'h3'
import { internalJwtSecret } from './internalJwt'

export interface SessionUser {
  username: string
  displayName: string
  email: string
  roles: { role: string, projectId: number | null }[]
  projectIds: number[]
}

interface SessionPayload {
  user: SessionUser
  exp: number // 秒级时间戳
}

const COOKIE_NAME = 'devflow_session'
const MAX_AGE_SECONDS = 8 * 60 * 60 // 一个工作日；到期重新走 LDAP 登录

function sign(data: string): string {
  return createHmac('sha256', `${internalJwtSecret()}:session`).update(data).digest('base64url')
}

export function setSession(event: H3Event, user: SessionUser): void {
  const payload: SessionPayload = {
    user,
    exp: Math.floor(Date.now() / 1000) + MAX_AGE_SECONDS,
  }
  const data = Buffer.from(JSON.stringify(payload)).toString('base64url')
  setCookie(event, COOKIE_NAME, `${data}.${sign(data)}`, {
    httpOnly: true,
    sameSite: 'lax',
    secure: !import.meta.dev,
    path: '/',
    maxAge: MAX_AGE_SECONDS,
  })
}

export function clearSession(event: H3Event): void {
  deleteCookie(event, COOKIE_NAME, { path: '/' })
}

export function getSession(event: H3Event): SessionUser | null {
  const raw = getCookie(event, COOKIE_NAME)
  if (!raw) return null
  const dot = raw.lastIndexOf('.')
  if (dot < 0) return null
  const data = raw.slice(0, dot)
  const signature = Buffer.from(raw.slice(dot + 1))
  const expected = Buffer.from(sign(data))
  if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) return null
  try {
    const payload = JSON.parse(Buffer.from(data, 'base64url').toString()) as SessionPayload
    if (!payload.user || payload.exp * 1000 < Date.now()) return null
    return payload.user
  } catch {
    return null
  }
}
