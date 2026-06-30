// Ported from src/app/api/wiki/projects/route.ts (GET).
// Lists processed wiki projects from the Python backend cache.
export default defineEventHandler(async (event) => {
  const endpoint = `${pythonBackendHost()}/api/processed_projects`
  try {
    const response = await fetch(endpoint, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })

    if (!response.ok) {
      let errorBody: unknown = { error: `Failed to fetch from Python backend: ${response.statusText}` }
      try {
        errorBody = await response.json()
      } catch {
        // keep the default error body
      }
      console.error(`Error from Python backend (${endpoint}): ${response.status} - ${JSON.stringify(errorBody)}`)
      setResponseStatus(event, response.status)
      return errorBody
    }

    return await response.json()
  } catch (error: unknown) {
    console.error(`Network or other error when fetching from ${endpoint}:`, error)
    const message = error instanceof Error ? error.message : 'An unknown error occurred'
    setResponseStatus(event, 503)
    return { error: `Failed to connect to the Python backend. ${message}` }
  }
})
