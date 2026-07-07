// /api/reviews/**（详情、conclude 结论录入）→ requirement 服务。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
