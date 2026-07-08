// 对话建需求的 agentic 聊天通道：SSE 透传到 api 服务（工具循环 + 引用核验）。
export default defineEventHandler(async (event) => {
  if (authEnabled() && !getSessionUser(event)) {
    throw createError({ statusCode: 401, statusMessage: 'not authenticated' })
  }
  const body = await readBody(event)
  const resp = await fetch(`${serverBaseUrl()}/api/chat/agentic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) {
    setResponseStatus(event, resp.status || 502)
    return await resp.text().catch(() => 'agentic chat upstream error')
  }
  setResponseHeader(event, 'Content-Type', 'text/event-stream')
  setResponseHeader(event, 'Cache-Control', 'no-cache, no-transform')
  return resp.body
})
