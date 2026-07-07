// 删除追溯报告 → 后端 DELETE /api/trace_reports/{id} 透传。
export default defineEventHandler(async (event) => {
  const id = encodeURIComponent(getRouterParam(event, 'id') || '')
  try {
    const response = await fetch(`${serverBaseUrl()}/api/trace_reports/${id}`, { method: 'DELETE' })
    if (!response.ok) {
      setResponseStatus(event, response.status)
      try { return await response.json() } catch { return { error: response.statusText } }
    }
    return await response.json()
  } catch (error) {
    setResponseStatus(event, 503)
    return { error: error instanceof Error ? error.message : 'Failed to connect to the Python backend.' }
  }
})
