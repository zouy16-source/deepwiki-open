// One WebSocket-with-HTTP-fallback streaming helper, factored out of the three
// near-identical copies in the old page.tsx (page-content gen, structure gen, Ask).
// Returns the full accumulated text; onChunk fires with the running total.

export interface ChatStreamRequest {
  repo_url: string
  type?: string
  messages: { role: string; content: string }[]
  [key: string]: unknown
}

export async function streamChat(
  baseUrl: string,
  request: ChatStreamRequest,
  onChunk?: (full: string) => void,
): Promise<string> {
  const wsUrl = `${(baseUrl || 'http://localhost:8001').replace(/^http/, 'ws')}/ws/chat`
  let content = ''

  try {
    const ws = new WebSocket(wsUrl)

    // Connect (5s timeout, then fall back to HTTP).
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000)
      ws.onopen = () => {
        clearTimeout(timeout)
        ws.send(JSON.stringify(request))
        resolve()
      }
      ws.onerror = () => {
        clearTimeout(timeout)
        reject(new Error('WebSocket connection failed'))
      }
    })

    // Receive until the socket closes.
    await new Promise<void>((resolve, reject) => {
      ws.onmessage = (event) => {
        content += event.data
        onChunk?.(content)
      }
      ws.onclose = () => resolve()
      ws.onerror = () => reject(new Error('WebSocket error during message reception'))
    })

    return content
  } catch {
    // HTTP/SSE fallback via the Nitro proxy.
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      const errorText = await response.text().catch(() => 'No error details available')
      throw new Error(`Error from chat stream: ${response.status} - ${errorText}`)
    }
    const reader = response.body?.getReader()
    if (!reader) throw new Error('Failed to get response reader')
    const decoder = new TextDecoder()
    content = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      content += decoder.decode(value, { stream: true })
      onChunk?.(content)
    }
    content += decoder.decode()
    return content
  }
}
