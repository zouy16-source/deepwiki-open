// Ported from src/app/api/models/config/route.ts. Forwards the model config.
export default defineEventHandler(async (event) => {
  try {
    const backendResponse = await fetch(`${serverBaseUrl()}/models/config`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    if (!backendResponse.ok) {
      setResponseStatus(event, backendResponse.status)
      return { error: `Backend service responded with status: ${backendResponse.status}` }
    }
    return await backendResponse.json()
  } catch (error) {
    console.error('Error fetching model configurations:', error)
    setResponseStatus(event, 500)
    return { error: String(error) }
  }
})
