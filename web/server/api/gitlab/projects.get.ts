// Ported from src/app/api/gitlab/projects/route.ts.
// Proxies to the Python backend's GitLab project catalog endpoint.
export default defineEventHandler(async (event) => {
  const q = getQuery(event)
  const qs = new URLSearchParams()
  qs.set('search', String(q.search || ''))
  qs.set('page', String(q.page || '1'))

  const endpoint = `${pythonBackendHost()}/api/gitlab/projects?${qs.toString()}`
  try {
    const response = await fetch(endpoint, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })
    const data = await response.json()
    setResponseStatus(event, response.status)
    return data
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'An unknown error occurred'
    setResponseStatus(event, 503)
    return { projects: [], nextPage: null, error: `Failed to connect to backend. ${message}` }
  }
})
