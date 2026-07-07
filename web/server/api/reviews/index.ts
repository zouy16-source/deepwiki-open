// /api/reviews → requirement 服务（评审单）。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
