// /api/users → identity 服务（全部方法）。
export default defineEventHandler(event => proxyPlatformService(event, identityBaseUrl()))
