// 历史追溯报告列表 → 后端 /api/trace_reports 透传（query 原样带过去）。
export default defineEventHandler(async (event) => {
  const qs = new URLSearchParams(getQuery(event) as Record<string, string>).toString()
  const endpoint = `${serverBaseUrl()}/api/trace_reports${qs ? `?${qs}` : ''}`
  try {
    const response = await fetch(endpoint, { cache: 'no-store' })
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
