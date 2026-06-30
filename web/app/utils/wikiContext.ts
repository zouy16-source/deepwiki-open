// Shared between the slides + workshop pages: load the cached wiki and assemble a
// size-capped context string (high-importance pages first). Ported from the
// identical fetchCachedWikiContent + content-assembly in both page.tsx files.

export interface CachedWikiPage { id: string; title: string; importance: string; content?: string }
export interface CachedWiki {
  wiki_structure: { description?: string; pages?: CachedWikiPage[] }
  generated_pages: Record<string, { content?: string }>
}

export async function fetchCachedWiki(
  owner: string,
  repo: string,
  type: string,
  language: string,
): Promise<CachedWiki | null> {
  try {
    const params = new URLSearchParams({ owner, repo, repo_type: type, language })
    const data = await $fetch<CachedWiki>(`/api/wiki_cache?${params.toString()}`)
    if (data?.wiki_structure && data.generated_pages && Object.keys(data.generated_pages).length > 0) {
      return data
    }
    return null
  } catch {
    return null
  }
}

export function buildWikiContext(wikiData: CachedWiki | null): string {
  if (!wikiData?.wiki_structure || !wikiData.generated_pages) return ''
  let ctx = `## Project Overview\n${wikiData.wiki_structure.description || ''}\n\n`
  const pages = wikiData.wiki_structure.pages || []
  const gen = wikiData.generated_pages
  let total = 0
  const max = 30000 // approximate token guard

  for (const page of pages.filter((p) => p.importance === 'high')) {
    const c = gen[page.id]?.content
    if (!c) continue
    const block = `## ${page.title}\n${c}\n\n`
    ctx += block
    total += block.length
    if (total > max) break
  }

  if (total < max) {
    for (const page of pages) {
      if (page.importance === 'high') continue
      const c = gen[page.id]?.content
      if (!c) continue
      const full = `## ${page.title}\n${c}\n\n`
      if (total + full.length > max) {
        const m = c.match(/# .*?\n\n(.*?)(\n\n|$)/)
        const summary = m ? m[1].trim() : 'No summary available'
        const block = `## ${page.title}\n${summary}\n\n`
        ctx += block
        total += block.length
      } else {
        ctx += full
        total += full.length
      }
      if (total > max) break
    }
  }
  return ctx
}
