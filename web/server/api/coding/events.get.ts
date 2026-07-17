// AI 编码进度 SSE：透传 dev 服务的进度流(/internal/coding/runs/{run_id}/events)。
// 前端订阅 /api/coding/events?run_id=X;会话鉴权在 BFF,内部端点直连 dev(:8004)。
export default defineEventHandler(async (event) => {
  if (authEnabled() && !getSessionUser(event)) {
    throw createError({ statusCode: 401, statusMessage: 'not authenticated' })
  }
  const runId = Number(getQuery(event).run_id)
  if (!runId) {
    throw createError({ statusCode: 400, statusMessage: 'run_id required' })
  }
  const resp = await fetch(`${devBaseUrl()}/internal/coding/runs/${runId}/events`, {
    headers: { Accept: 'text/event-stream' },
  })
  if (!resp.ok || !resp.body) {
    setResponseStatus(event, resp.status || 502)
    return await resp.text().catch(() => 'coding events upstream error')
  }
  setResponseHeader(event, 'Content-Type', 'text/event-stream')
  setResponseHeader(event, 'Cache-Control', 'no-cache, no-transform')
  return resp.body
})
