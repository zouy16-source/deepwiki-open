// Ported from src/app/api/chat/stream/route.ts.
// HTTP/SSE fallback for chat completions (the primary path is the WebSocket client).
// Streams the backend's response body straight through to the client.
export default defineEventHandler(async (event) => {
  try {
    const requestBody = await readBody(event)
    const targetUrl = `${serverBaseUrl()}/chat/completions/stream`

    const backendResponse = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(requestBody),
    })

    // Forward backend errors verbatim.
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

    setResponseStatus(event, backendResponse.status)
    const contentType = backendResponse.headers.get('Content-Type')
    if (contentType) setResponseHeader(event, 'Content-Type', contentType)
    setResponseHeader(event, 'Cache-Control', 'no-cache, no-transform')

    // Returning a ReadableStream makes Nitro stream it to the client.
    return backendResponse.body
  } catch (error) {
    console.error('Error in API proxy route (/api/chat/stream):', error)
    const message = error instanceof Error ? error.message : 'Internal Server Error in proxy'
    setResponseStatus(event, 500)
    return { error: message }
  }
})
