// /api/tapd/**（TAPD 同步）→ requirement 服务。
export default defineEventHandler(event => proxyPlatformService(event, requirementBaseUrl()))
