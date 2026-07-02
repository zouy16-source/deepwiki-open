// Wiki domain types — ported from the inline types in
// src/app/[owner]/[repo]/page.tsx and src/types/repoinfo.tsx.

export interface RepoInfo {
  owner: string
  repo: string
  type: string
  token: string | null
  localPath: string | null
  repoUrl: string | null
}

// Page archetype — selects a distinct body structure (see buildPagePrompt) so pages
// don't all read the same. Keep in sync with api/wiki_generator.py PAGE_TYPES.
export type PageType = 'overview' | 'architecture' | 'feature' | 'reference' | 'cross-cutting' | 'guide' | 'glossary'

export interface WikiPage {
  id: string
  title: string
  content: string
  filePaths: string[]
  importance: 'high' | 'medium' | 'low'
  relatedPages: string[]
  type?: PageType
  edited?: boolean         // manually edited (locked from full regeneration)
  updated_at?: number      // unix ms of last edit / single-page regenerate
  prev_content?: string    // previous content, for one-level revert
  parentId?: string
  isSection?: boolean
  children?: string[]
}

// One entry in a page's change timeline (from GET /api/wiki/page/history).
export interface HistoryEntry {
  at: number                                                   // unix ms
  action: 'generated' | 'regenerated' | 'edited' | 'reverted'
  source: 'ai' | 'human'
  actor?: string | null                                        // who — null until auth
  model?: string | null                                        // the AI "who"
  provider?: string | null
  summary?: string
  size?: number
  content?: string | null                                      // snapshot, for diff/revert
}

export interface WikiSection {
  id: string
  title: string
  pages: string[]
  subsections?: string[]
}

export interface WikiStructure {
  id: string
  title: string
  description: string
  pages: WikiPage[]
  sections: WikiSection[]
  rootSections: string[]
}
