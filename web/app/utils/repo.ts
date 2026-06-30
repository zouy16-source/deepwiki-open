// Repo helpers ported from src/utils/getRepoUrl.tsx, src/utils/urlDecoder.tsx and
// the inline helpers in src/app/[owner]/[repo]/page.tsx. Auto-imported by Nuxt.
import type { RepoInfo } from '~/types/wiki'

export function getRepoUrl(repoInfo: RepoInfo): string {
  if (repoInfo.type === 'local' && repoInfo.localPath) return repoInfo.localPath
  if (repoInfo.repoUrl) return repoInfo.repoUrl
  if (repoInfo.owner && repoInfo.repo) return `http://example/${repoInfo.owner}/${repoInfo.repo}`
  return ''
}

export function extractUrlPath(input: string): string | null {
  try {
    const normalized = input.startsWith('http') ? input : `https://${input}`
    return new URL(normalized).pathname.replace(/^\/|\/$/g, '')
  } catch {
    return null
  }
}

export function getCacheKey(
  owner: string,
  repo: string,
  repoType: string,
  language: string,
  isComprehensive = true,
): string {
  return `deepwiki_cache_${repoType}_${owner}_${repo}_${language}_${isComprehensive ? 'comprehensive' : 'concise'}`
}

// Human-readable language label used inside the generation prompts.
const LANGUAGE_LABELS: Record<string, string> = {
  en: 'English',
  ja: 'Japanese (日本語)',
  zh: 'Mandarin Chinese (中文)',
  'zh-tw': 'Traditional Chinese (繁體中文)',
  es: 'Spanish (Español)',
  kr: 'Korean (한국어)',
  vi: 'Vietnamese (Tiếng Việt)',
  'pt-br': 'Brazilian Portuguese (Português Brasileiro)',
  fr: 'Français (French)',
  ru: 'Русский (Russian)',
}

export function languageLabel(code: string): string {
  return LANGUAGE_LABELS[code] || 'English'
}

export interface ChatRequestExtras {
  token?: string
  provider?: string
  model?: string
  isCustomModel?: boolean
  customModel?: string
  language?: string
  excludedDirs?: string
  excludedFiles?: string
  includedDirs?: string
  includedFiles?: string
}

// Ported from addTokensToRequestBody (object form for clarity).
export function addTokensToRequestBody(
  body: Record<string, unknown>,
  opts: ChatRequestExtras,
): void {
  if (opts.token) body.token = opts.token
  body.provider = opts.provider || ''
  body.model = opts.model || ''
  if (opts.isCustomModel && opts.customModel) body.custom_model = opts.customModel
  body.language = opts.language || 'en'
  if (opts.excludedDirs) body.excluded_dirs = opts.excludedDirs
  if (opts.excludedFiles) body.excluded_files = opts.excludedFiles
  if (opts.includedDirs) body.included_dirs = opts.includedDirs
  if (opts.includedFiles) body.included_files = opts.includedFiles
}

export function createGithubHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/vnd.github.v3+json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

export function createBitbucketHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}
