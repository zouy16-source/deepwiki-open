// Ported from src/app/api/auth/status/route.ts. Forwards to the backend auth status.
export default defineEventHandler(async (event) => {
  try {
    const response = await fetch(`${serverBaseUrl()}/auth/status`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      setResponseStatus(event, response.status)
      return { error: `Backend server returned ${response.status}` }
    }
    return await response.json()
  } catch (error) {
    console.error('Error forwarding request to backend:', error)
    setResponseStatus(event, 500)
    return { error: 'Internal Server Error' }
  }
})
