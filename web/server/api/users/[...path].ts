// /api/users/**（含 /api/users/me，identity 从内部 JWT sub 解出当前用户）。
export default defineEventHandler(event => proxyPlatformService(event, identityBaseUrl()))
