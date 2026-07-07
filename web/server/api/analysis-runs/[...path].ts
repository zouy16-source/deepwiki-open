// /api/analysis-runs/**（分析报告详情）→ requirement 服务。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
