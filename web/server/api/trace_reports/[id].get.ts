// 单份追溯报告 → 后端 /api/trace_reports/{id} 透传。
export default defineEventHandler(async (event) => {
  const id = encodeURIComponent(getRouterParam(event, 'id') || '')
  try {
    const response = await fetch(`${serverBaseUrl()}/api/trace_reports/${id}`, { cache: 'no-store' })
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
