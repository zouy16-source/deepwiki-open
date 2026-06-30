// Ported from src/app/api/gitlab/file_tree/route.ts.
// Proxies to the Python backend's GitLab file-tree endpoint.
export default defineEventHandler(async (event) => {
  const q = getQuery(event)
  const qs = new URLSearchParams()
  qs.set('repo_url', String(q.repo_url || ''))
  if (q.token) qs.set('token', String(q.token))

  try {
    const response = await fetch(`${pythonBackendHost()}/api/gitlab/file_tree?${qs.toString()}`, {
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
    return { error: `Failed to connect to backend. ${message}`, file_tree: '', default_branch: 'main', readme: '' }
  }
})
