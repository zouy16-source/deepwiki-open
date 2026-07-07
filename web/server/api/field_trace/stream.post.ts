// 字段追溯 v2 流式代理：把后端 /api/field_trace/stream 的 NDJSON 进度流
// 原样透传给浏览器（同 chat/stream 的模式——返回 ReadableStream 即流式）。
export default defineEventHandler(async (event) => {
  try {
    const requestBody = await readBody(event)
    const backendResponse = await fetch(`${serverBaseUrl()}/api/field_trace/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })

    if (!backendResponse.ok) {
      const errorBody = await backendResponse.text()
      setResponseStatus(event, backendResponse.status)
      const ct = backendResponse.headers.get('Content-Type')
      if (ct) setResponseHeader(event, 'Content-Type', ct)
      return errorBody
    }

    if (!backendResponse.body) {
      setResponseStatus(event, 500)
      return 'Stream body from backend is null'
    }

    setResponseHeader(event, 'Content-Type', 'application/x-ndjson')
    setResponseHeader(event, 'Cache-Control', 'no-cache, no-transform')
    return backendResponse.body
  } catch (error) {
    console.error('Error in API proxy route (/api/field_trace/stream):', error)
    setResponseStatus(event, 500)
    return { error: error instanceof Error ? error.message : 'Internal Server Error in proxy' }
  }
})
