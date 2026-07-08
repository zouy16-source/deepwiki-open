// 对话 → 需求草稿：转发到 api 服务的结构化提取端点（一次 LLM 调用）。
export default defineEventHandler(async (event) => {
  if (authEnabled() && !getSessionUser(event)) {
    throw createError({ statusCode: 401, statusMessage: 'not authenticated' })
  }
  const body = await readBody(event)
  return await $fetch(`${serverBaseUrl()}/api/analysis/requirement-draft`, {
    method: 'POST',
    body,
    timeout: 60_000,
  })
})
