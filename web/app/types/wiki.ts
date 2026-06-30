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

export interface WikiPage {
  id: string
  title: string
  content: string
  filePaths: string[]
  importance: 'high' | 'medium' | 'low'
  relatedPages: string[]
  parentId?: string
  isSection?: boolean
  children?: string[]
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
