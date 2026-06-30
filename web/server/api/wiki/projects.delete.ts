// Ported from src/app/api/wiki/projects/route.ts (DELETE).
// Deletes a project's wiki cache via the Python backend.
interface DeleteProjectCachePayload {
  owner: string
  repo: string
  repo_type: string
  language: string
}

function isDeleteProjectCachePayload(obj: unknown): obj is DeleteProjectCachePayload {
  if (obj == null || typeof obj !== 'object') return false
  const o = obj as Record<string, unknown>
  const nonEmpty = (v: unknown) => typeof v === 'string' && v.trim() !== ''
  return nonEmpty(o.owner) && nonEmpty(o.repo) && nonEmpty(o.repo_type) && nonEmpty(o.language)
}

export default defineEventHandler(async (event) => {
  try {
    const body: unknown = await readBody(event)
    if (!isDeleteProjectCachePayload(body)) {
      setResponseStatus(event, 400)
      return { error: 'Invalid request body: owner, repo, repo_type, and language are required and must be non-empty strings.' }
    }
    const { owner, repo, repo_type, language } = body
    const params = new URLSearchParams({ owner, repo, repo_type, language })
    const response = await fetch(`${pythonBackendHost()}/api/wiki_cache?${params}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      let errorBody: unknown = { error: response.statusText }
      try {
        errorBody = await response.json()
      } catch {
        // keep the default error body
      }
      console.error(`Error deleting project cache: ${response.status} - ${JSON.stringify(errorBody)}`)
      setResponseStatus(event, response.status)
      return errorBody
    }
    return { message: 'Project deleted successfully' }
  } catch (error: unknown) {
    console.error('Error in DELETE /api/wiki/projects:', error)
    const message = error instanceof Error ? error.message : 'An unknown error occurred'
    setResponseStatus(event, 500)
    return { error: `Failed to delete project: ${message}` }
  }
})
