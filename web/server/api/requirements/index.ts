// /api/requirements → requirement 服务（全部方法）。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
