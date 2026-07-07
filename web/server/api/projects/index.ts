// /api/projects → identity 服务（项目空间）。
export default defineEventHandler(event => proxyPlatformService(event, identityBaseUrl()))
