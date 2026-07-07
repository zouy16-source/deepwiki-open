// Backend/origin resolution for the BFF handlers. Reads the SAME env var names the
// old Next.js routes used, at request time, so existing .env / docker-compose configs
// work unchanged:
//   SERVER_BASE_URL     - auth/*, models/config, chat/stream  (default :8001)
//   PYTHON_BACKEND_HOST - gitlab/*, wiki/projects             (default :8001)
//   GITLAB_URL / GITLAB_TOKEN - direct GitLab API (default_branch)

export function serverBaseUrl(): string {
  return process.env.SERVER_BASE_URL || 'http://localhost:8001'
}

export function pythonBackendHost(): string {
  return process.env.PYTHON_BACKEND_HOST || 'http://localhost:8001'
}

// identity 服务（services/identity：登录认证 + RBAC + 审计），端口约定见 services/README.md。
export function identityBaseUrl(): string {
  return process.env.IDENTITY_BASE_URL || 'http://localhost:8003'
}

// requirement 服务（services/requirement：需求流转 + 评审），端口约定见 services/README.md。
export function requirementBaseUrl(): string {
  return process.env.REQUIREMENT_BASE_URL || 'http://localhost:8002'
}

export function gitlabUrl(): string {
  return (process.env.GITLAB_URL || 'https://gitlab.com').replace(/\/+$/, '')
}

export function gitlabToken(): string {
  return process.env.GITLAB_TOKEN || ''
}
