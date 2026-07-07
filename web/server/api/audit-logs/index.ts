// /api/audit-logs → identity 服务（审计）。
export default defineEventHandler(event => proxyPlatformService(event, identityBaseUrl()))
