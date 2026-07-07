// /api/requirements/** → requirement 服务（详情、transitions、events 等）。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
