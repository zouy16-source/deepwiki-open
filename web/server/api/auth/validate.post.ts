// Ported from src/app/api/auth/validate/route.ts. Forwards the auth code to the backend.
export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    const response = await fetch(`${serverBaseUrl()}/auth/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
