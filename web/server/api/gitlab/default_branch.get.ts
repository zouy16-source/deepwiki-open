// Ported from src/app/api/gitlab/default_branch/route.ts.
// Returns a GitLab repo's default branch by calling the GitLab API v4 directly
// (server-side, with GITLAB_TOKEN), so private self-hosted GitLab works without
// browser CORS/token issues.
export default defineEventHandler(async (event) => {
  const q = getQuery(event)
  const owner = String(q.owner || '')
  const repo = String(q.repo || '')
  const repoUrlParam = String(q.repo_url || '')
  const token = String(q.token || gitlabToken())

  // Resolve base host + project path (prefer explicit repo_url; force https).
  let base = gitlabUrl()
  let projectPath = ''
  if (repoUrlParam) {
    try {
      const u = new URL(repoUrlParam)
      base = `https://${u.host}`
      projectPath = u.pathname.replace(/^\/+/, '').replace(/\.git$/, '')
    } catch {
      projectPath = repoUrlParam.replace(/^\/+/, '').replace(/\.git$/, '')
    }
  } else if (owner && repo) {
    projectPath = `${owner}/${repo}`
  }

  if (!projectPath) {
    setResponseStatus(event, 400)
    return { error: 'owner/repo or repo_url required', default_branch: null }
  }

  const api = `${base}/api/v4/projects/${encodeURIComponent(projectPath)}`
  try {
    const res = await fetch(api, {
      headers: token ? { 'PRIVATE-TOKEN': token } : {},
      cache: 'no-store',
    })
    // Mirror the original: GitLab/network failures resolve as 200 with null branch.
    if (!res.ok) {
      return { error: `GitLab HTTP ${res.status}`, default_branch: null }
    }
    const data = await res.json() as { default_branch?: string; web_url?: string }
    return { default_branch: data.default_branch || null, web_url: data.web_url || null }
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'unknown error'
    return { error: message, default_branch: null }
  }
})
