// /api/audit-logs/** → identity 服务。
export default defineEventHandler(event => proxyPlatformService(event, identityBaseUrl()))
