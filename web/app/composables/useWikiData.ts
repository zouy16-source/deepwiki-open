// Orchestrates the wiki page data: load from server cache, else fetch the repo
// structure and generate pages over WebSocket, plus export. Ported from the
// stateful logic of src/app/[owner]/[repo]/page.tsx (the render lives in the page).
import type { HistoryEntry, RepoInfo, WikiPage, WikiSection, WikiStructure } from '~/types/wiki'

export interface WikiDataOptions {
  owner: string
  repo: string
  repoInfo: RepoInfo
  language: string
  isComprehensive: boolean
  token: string
  provider: string
  model: string
  isCustomModel: boolean
  customModel: string
  excludedDirs: string
  excludedFiles: string
  includedDirs: string
  includedFiles: string
}

export function useWikiData(opts: WikiDataOptions) {
  const baseUrl = (useRuntimeConfig().public.serverBaseUrl as string) || 'http://localhost:8001'

  const isLoading = ref(true)
  const loadingMessage = ref<string | undefined>('Initializing wiki generation...')
  const error = ref<string | null>(null)
  const embeddingError = ref(false)
  const wikiStructure = ref<WikiStructure | undefined>()
  const currentPageId = ref<string | undefined>()
  const generatedPages = ref<Record<string, WikiPage>>({})
  const pagesInProgress = ref<Set<string>>(new Set())
  const effectiveRepoInfo = ref<RepoInfo>(opts.repoInfo)
  const defaultBranch = ref('main')
  const currentToken = ref(opts.token)
  const isExporting = ref(false)
  const exportError = ref<string | null>(null)
  const provider = ref(opts.provider)
  const model = ref(opts.model)

  const activeContentRequests = new Map<string, boolean>()
  let structureRequestInProgress = false
  let requestInProgress = false
  let cacheLoaded = false

  // --- file URL (source-link resolver passed to <Markdown>) ---
  function generateFileUrl(filePath: string): string {
    const info = effectiveRepoInfo.value
    if (info.type === 'local') return filePath
    const raw = info.repoUrl
    if (!raw) return filePath
    const url = raw.replace(/^http:\/\//i, 'https://')
    let kind = info.type
    if (kind !== 'github' && kind !== 'gitlab' && kind !== 'bitbucket') {
      try {
        const host = new URL(url).hostname
        kind = host.includes('gitlab') ? 'gitlab' : host.includes('bitbucket') ? 'bitbucket' : 'github'
      } catch {
        kind = 'github'
      }
    }
    const clean = filePath.replace(/^\//, '')
    if (kind === 'gitlab') return `${url}/-/blob/${defaultBranch.value}/${clean}`
    if (kind === 'bitbucket') return `${url}/src/${defaultBranch.value}/${clean}`
    return `${url}/blob/${defaultBranch.value}/${clean}`
  }

  function buildRequest(content: string): ChatStreamRequest {
    const body: ChatStreamRequest = {
      repo_url: getRepoUrl(effectiveRepoInfo.value),
      type: effectiveRepoInfo.value.type,
      messages: [{ role: 'user', content }],
    }
    addTokensToRequestBody(body, {
      token: currentToken.value,
      provider: provider.value,
      model: model.value,
      isCustomModel: opts.isCustomModel,
      customModel: opts.customModel,
      language: opts.language,
      excludedDirs: opts.excludedDirs,
      excludedFiles: opts.excludedFiles,
      includedDirs: opts.includedDirs,
      includedFiles: opts.includedFiles,
    })
    return body
  }

  // --- per-page content generation ---
  async function generatePageContent(page: WikiPage) {
    if (generatedPages.value[page.id]?.content) return
    if (activeContentRequests.get(page.id)) return
    activeContentRequests.set(page.id, true)
    pagesInProgress.value = new Set(pagesInProgress.value).add(page.id)
    generatedPages.value = { ...generatedPages.value, [page.id]: { ...page, content: 'Loading...' } }
    try {
      const filePathsList = page.filePaths.map((p) => `- [${p}](${generateFileUrl(p)})`).join('\n')
      const prompt = buildPagePrompt({ pageTitle: page.title, filePathsList, pageType: page.type })
      let content = await streamChat(baseUrl, buildRequest(prompt))
      content = content.replace(/^```markdown\s*/i, '').replace(/```\s*$/i, '')
      generatedPages.value = { ...generatedPages.value, [page.id]: { ...page, content } }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      generatedPages.value = { ...generatedPages.value, [page.id]: { ...page, content: `Error generating content: ${msg}` } }
      error.value = `Failed to generate content for ${page.title}.`
    } finally {
      activeContentRequests.delete(page.id)
      const next = new Set(pagesInProgress.value)
      next.delete(page.id)
      pagesInProgress.value = next
      loadingMessage.value = undefined
    }
  }

  // --- structure determination (XML) + sequential page generation ---
  async function determineWikiStructure(fileTree: string, readme: string) {
    if (structureRequestInProgress) return
    try {
      structureRequestInProgress = true
      loadingMessage.value = 'Determining wiki structure...'
      const prompt = buildStructurePrompt({
        owner: opts.owner,
        repo: opts.repo,
        fileTree,
        readme,
        isComprehensive: opts.isComprehensive,
      })
      let responseText = await streamChat(baseUrl, buildRequest(prompt))

      if (responseText.includes('Error preparing retriever') && responseText.includes('OPENAI_API_KEY')) {
        embeddingError.value = true
        throw new Error('OPENAI_API_KEY environment variable is not set. Please configure your API key.')
      }
      if (responseText.includes('Ollama model') && responseText.includes('not found')) {
        embeddingError.value = true
        throw new Error('The specified Ollama embedding model was not found.')
      }

      responseText = responseText.replace(/^```(?:xml)?\s*/i, '').replace(/```\s*$/i, '')
      const xmlMatch = responseText.match(/<wiki_structure>[\s\S]*?<\/wiki_structure>/m)
      if (!xmlMatch) throw new Error('No valid XML found in response')
      const xmlText = xmlMatch[0].replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
      const xmlDoc = new DOMParser().parseFromString(xmlText, 'text/xml')

      const title = xmlDoc.querySelector('title')?.textContent || ''
      const description = xmlDoc.querySelector('description')?.textContent || ''
      const pages: WikiPage[] = []
      xmlDoc.querySelectorAll('page').forEach((pageEl) => {
        const id = pageEl.getAttribute('id') || `page-${pages.length + 1}`
        const pTitle = pageEl.querySelector('title')?.textContent || ''
        const impText = pageEl.querySelector('importance')?.textContent
        const importance = impText === 'high' ? 'high' : impText === 'low' ? 'low' : 'medium'
        const type = normalizePageType(pageEl.querySelector('type')?.textContent || undefined)
        const filePaths: string[] = []
        pageEl.querySelectorAll('file_path').forEach((el) => el.textContent && filePaths.push(el.textContent))
        const relatedPages: string[] = []
        pageEl.querySelectorAll('related').forEach((el) => el.textContent && relatedPages.push(el.textContent))
        pages.push({ id, title: pTitle, content: '', filePaths, importance, relatedPages, type })
      })

      const sections: WikiSection[] = []
      const rootSections: string[] = []
      if (opts.isComprehensive) {
        const sectionEls = xmlDoc.querySelectorAll('section')
        sectionEls.forEach((sectionEl) => {
          const id = sectionEl.getAttribute('id') || `section-${sections.length + 1}`
          const sTitle = sectionEl.querySelector('title')?.textContent || ''
          const secPages: string[] = []
          const subsections: string[] = []
          sectionEl.querySelectorAll('page_ref').forEach((el) => el.textContent && secPages.push(el.textContent))
          sectionEl.querySelectorAll('section_ref').forEach((el) => el.textContent && subsections.push(el.textContent))
          sections.push({ id, title: sTitle, pages: secPages, subsections: subsections.length ? subsections : undefined })
          let referenced = false
          sectionEls.forEach((other) =>
            other.querySelectorAll('section_ref').forEach((ref) => {
              if (ref.textContent === id) referenced = true
            }),
          )
          if (!referenced) rootSections.push(id)
        })
      }

      const structure: WikiStructure = { id: 'wiki', title, description, pages, sections, rootSections }
      wikiStructure.value = structure
      currentPageId.value = pages.length ? pages[0].id : undefined

      if (pages.length) {
        pagesInProgress.value = new Set(pages.map((p) => p.id))
        // MAX_CONCURRENT = 1 in the original -> sequential is equivalent and simpler.
        for (const page of pages) {
          await generatePageContent(page)
        }
        isLoading.value = false
        loadingMessage.value = undefined
        await saveCache()
      } else {
        isLoading.value = false
        loadingMessage.value = undefined
      }
    } catch (err) {
      isLoading.value = false
      error.value = err instanceof Error ? err.message : 'An unknown error occurred'
      loadingMessage.value = undefined
    } finally {
      structureRequestInProgress = false
    }
  }

  // --- repo structure fetch (per provider) ---
  async function fetchRepositoryStructure() {
    if (requestInProgress) return
    wikiStructure.value = undefined
    currentPageId.value = undefined
    generatedPages.value = {}
    pagesInProgress.value = new Set()
    error.value = null
    embeddingError.value = false
    try {
      requestInProgress = true
      isLoading.value = true
      loadingMessage.value = 'Fetching repository structure...'
      const info = effectiveRepoInfo.value
      let fileTree = ''
      let readme = ''

      if (info.type === 'local' && info.localPath) {
        const res = await fetch(`/local_repo/structure?path=${encodeURIComponent(info.localPath)}`)
        if (!res.ok) throw new Error(`Local repository API error (${res.status}): ${await res.text()}`)
        const data = await res.json()
        fileTree = data.file_tree
        readme = data.readme
        defaultBranch.value = 'main'
      } else if (info.type === 'gitlab') {
        const params = new URLSearchParams()
        params.append('repo_url', info.repoUrl || `${opts.owner}/${opts.repo}`)
        if (currentToken.value) params.append('token', currentToken.value)
        const res = await fetch(`/api/gitlab/file_tree?${params.toString()}`)
        if (!res.ok) throw new Error(`Error fetching GitLab repository structure: ${await res.text()}`)
        const data = await res.json()
        if (data.error) throw new Error(data.error)
        fileTree = data.file_tree || ''
        readme = data.readme || ''
        defaultBranch.value = data.default_branch || 'main'
        if (!fileTree) throw new Error('Could not fetch repository structure. Repository might be empty or inaccessible.')
      } else if (info.type === 'github') {
        const apiBase = githubApiBase(info.repoUrl)
        let branch: string | null = null
        try {
          const r = await fetch(`${apiBase}/repos/${opts.owner}/${opts.repo}`, { headers: createGithubHeaders(currentToken.value) })
          if (r.ok) {
            branch = (await r.json()).default_branch
            defaultBranch.value = branch || 'main'
          }
        } catch { /* ignore */ }
        const branches = branch ? [branch, 'main', 'master'].filter((b, i, a) => a.indexOf(b) === i) : ['main', 'master']
        let tree: { tree?: { type: string; path: string }[] } | null = null
        let apiError = ''
        for (const b of branches) {
          const r = await fetch(`${apiBase}/repos/${opts.owner}/${opts.repo}/git/trees/${b}?recursive=1`, { headers: createGithubHeaders(currentToken.value) })
          if (r.ok) { tree = await r.json(); break }
          apiError = `Status: ${r.status}, Response: ${await r.text()}`
        }
        if (!tree?.tree) throw new Error(apiError ? `Could not fetch repository structure. API Error: ${apiError}` : 'Could not fetch repository structure. Repository might not exist, be empty or private.')
        fileTree = tree.tree.filter((i) => i.type === 'blob').map((i) => i.path).join('\n')
        try {
          const r = await fetch(`${apiBase}/repos/${opts.owner}/${opts.repo}/readme`, { headers: createGithubHeaders(currentToken.value) })
          if (r.ok) readme = atob((await r.json()).content)
        } catch { /* ignore */ }
      } else if (info.type === 'bitbucket') {
        const repoPath = extractUrlPath(info.repoUrl ?? '') ?? `${opts.owner}/${opts.repo}`
        const enc = encodeURIComponent(repoPath)
        const headers = createBitbucketHeaders(currentToken.value)
        const proj = await fetch(`https://api.bitbucket.org/2.0/repositories/${enc}`, { headers })
        if (!proj.ok) throw new Error(`Could not fetch repository structure. Bitbucket API Error: Status ${proj.status}`)
        const branch = (await proj.json()).mainbranch.name
        defaultBranch.value = branch
        const filesRes = await fetch(`https://api.bitbucket.org/2.0/repositories/${enc}/src/${branch}/?recursive=true&per_page=100`, { headers })
        const filesData = await filesRes.json()
        if (!Array.isArray(filesData.values) || !filesData.values.length) throw new Error('Could not fetch repository structure. Repository might not exist, be empty or private.')
        fileTree = filesData.values.filter((i: { type: string }) => i.type === 'commit_file').map((i: { path: string }) => i.path).join('\n')
        try {
          const r = await fetch(`https://api.bitbucket.org/2.0/repositories/${enc}/src/${branch}/README.md`, { headers })
          if (r.ok) readme = await r.text()
        } catch { /* ignore */ }
      }

      await determineWikiStructure(fileTree, readme)
    } catch (err) {
      isLoading.value = false
      error.value = err instanceof Error ? err.message : 'An unknown error occurred'
      loadingMessage.value = undefined
    } finally {
      requestInProgress = false
    }
  }

  function githubApiBase(repoUrl: string | null): string {
    if (!repoUrl) return 'https://api.github.com'
    try {
      const u = new URL(repoUrl)
      return u.hostname === 'github.com' ? 'https://api.github.com' : `${u.protocol}//${u.hostname}/api/v3`
    } catch {
      return 'https://api.github.com'
    }
  }

  // --- server cache load ---
  async function loadData() {
    loadingMessage.value = 'Checking for cached wiki...'
    try {
      const params = new URLSearchParams({
        owner: effectiveRepoInfo.value.owner,
        repo: effectiveRepoInfo.value.repo,
        repo_type: effectiveRepoInfo.value.type,
        language: opts.language,
        comprehensive: String(opts.isComprehensive),
      })
      const res = await fetch(`/api/wiki_cache?${params.toString()}`)
      if (res.ok) {
        const cached = await res.json()
        if (cached?.wiki_structure && cached.generated_pages && Object.keys(cached.generated_pages).length > 0) {
          if (cached.model) model.value = cached.model
          if (cached.provider) provider.value = cached.provider
          if (cached.repo) effectiveRepoInfo.value = cached.repo
          else if (cached.repo_url && !effectiveRepoInfo.value.repoUrl) {
            effectiveRepoInfo.value = { ...effectiveRepoInfo.value, repoUrl: cached.repo_url }
          }
          // Resolve the real default branch BEFORE rendering: citation links are
          // built at render time by generateFileUrl(), so if we render first the
          // links bake in the initial 'main' even when the repo uses 'master'.
          await refreshDefaultBranch()
          const structure: WikiStructure = {
            ...cached.wiki_structure,
            sections: cached.wiki_structure.sections || [],
            rootSections: cached.wiki_structure.rootSections || [],
          }
          if (!structure.sections.length || !structure.rootSections.length) ensureSections(structure)
          wikiStructure.value = structure
          generatedPages.value = cached.generated_pages
          currentPageId.value = structure.pages.length ? structure.pages[0].id : undefined
          isLoading.value = false
          loadingMessage.value = undefined
          cacheLoaded = true
          return
        }
      }
    } catch (err) {
      console.error('Error loading from server cache:', err)
    }
    // No cache -> generate.
    await fetchRepositoryStructure()
  }

  // Group pages into sections when the cache lacks them (ported from page.tsx).
  function ensureSections(structure: WikiStructure) {
    const categories = [
      { id: 'overview', title: 'Overview', keywords: ['overview', 'introduction', 'about'] },
      { id: 'architecture', title: 'Architecture', keywords: ['architecture', 'structure', 'design', 'system'] },
      { id: 'features', title: 'Core Features', keywords: ['feature', 'functionality', 'core'] },
      { id: 'components', title: 'Components', keywords: ['component', 'module', 'widget'] },
      { id: 'api', title: 'API', keywords: ['api', 'endpoint', 'service', 'server'] },
      { id: 'data', title: 'Data Flow', keywords: ['data', 'flow', 'pipeline', 'storage'] },
      { id: 'models', title: 'Models', keywords: ['model', 'ai', 'ml', 'integration'] },
      { id: 'ui', title: 'User Interface', keywords: ['ui', 'interface', 'frontend', 'page'] },
      { id: 'setup', title: 'Setup & Configuration', keywords: ['setup', 'config', 'installation', 'deploy'] },
    ]
    const clusters = new Map<string, WikiPage[]>()
    categories.forEach((c) => clusters.set(c.id, []))
    clusters.set('other', [])
    for (const page of structure.pages) {
      const title = page.title.toLowerCase()
      const cat = categories.find((c) => c.keywords.some((k) => title.includes(k)))
      clusters.get(cat ? cat.id : 'other')?.push(page)
    }
    const sections: WikiSection[] = []
    const rootSections: string[] = []
    for (const [id, pages] of clusters.entries()) {
      if (!pages.length) continue
      const cat = categories.find((c) => c.id === id) || { id, title: id === 'other' ? 'Other' : id }
      const sectionId = `section-${id}`
      sections.push({ id: sectionId, title: cat.title, pages: pages.map((p) => p.id) })
      rootSections.push(sectionId)
      pages.forEach((p) => (p.parentId = sectionId))
    }
    structure.sections = sections
    structure.rootSections = rootSections
  }

  async function refreshDefaultBranch() {
    if (effectiveRepoInfo.value.type !== 'gitlab') return
    const params = new URLSearchParams()
    if (effectiveRepoInfo.value.repoUrl) params.set('repo_url', effectiveRepoInfo.value.repoUrl)
    else { params.set('owner', opts.owner); params.set('repo', opts.repo) }
    if (currentToken.value) params.set('token', currentToken.value)
    try {
      const d = await $fetch<{ default_branch?: string }>(`/api/gitlab/default_branch?${params.toString()}`)
      if (d?.default_branch) defaultBranch.value = d.default_branch
    } catch { /* keep current */ }
  }

  // --- server cache save (after a fresh generation) ---
  async function saveCache() {
    if (cacheLoaded || !wikiStructure.value) return
    const pages = wikiStructure.value.pages
    const allHaveContent = pages.every(
      (p) => generatedPages.value[p.id]?.content && generatedPages.value[p.id].content !== 'Loading...',
    )
    if (!allHaveContent) return
    try {
      await $fetch('/api/wiki_cache', {
        method: 'POST',
        body: {
          repo: effectiveRepoInfo.value,
          language: opts.language,
          comprehensive: opts.isComprehensive,
          wiki_structure: { ...wikiStructure.value, sections: wikiStructure.value.sections || [], rootSections: wikiStructure.value.rootSections || [] },
          generated_pages: generatedPages.value,
          provider: provider.value,
          model: model.value,
        },
      })
    } catch (err) {
      console.error('Error saving to server cache:', err)
    }
  }

  // --- export ---
  async function exportWiki(format: 'markdown' | 'json') {
    if (!wikiStructure.value || !Object.keys(generatedPages.value).length) {
      exportError.value = 'No wiki content to export'
      return
    }
    try {
      isExporting.value = true
      exportError.value = null
      const pagesToExport = wikiStructure.value.pages.map((p) => ({
        ...p,
        content: generatedPages.value[p.id]?.content || 'Content not generated',
      }))
      const res = await fetch('/export/wiki', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: getRepoUrl(effectiveRepoInfo.value),
          type: effectiveRepoInfo.value.type,
          pages: pagesToExport,
          format,
        }),
      })
      if (!res.ok) throw new Error(`Error exporting wiki: ${res.status} - ${await res.text().catch(() => '')}`)
      let filename = `${effectiveRepoInfo.value.repo}_wiki.${format === 'markdown' ? 'md' : 'json'}`
      const cd = res.headers.get('Content-Disposition')
      const m = cd?.match(/filename=(.+)/)
      if (m?.[1]) filename = m[1].replace(/"/g, '')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      exportError.value = err instanceof Error ? err.message : 'Unknown error during export'
    } finally {
      isExporting.value = false
    }
  }

  function selectPage(id: string) {
    if (currentPageId.value !== id) currentPageId.value = id
  }

  // --- per-page edit / regenerate / revert (Wikipedia-style refinement) ---
  const pageBusy = ref<string | null>(null) // page id currently being acted on
  const pageActionError = ref<string | null>(null)

  function applyPageUpdate(page: WikiPage) {
    generatedPages.value = { ...generatedPages.value, [page.id]: page }
    const sp = wikiStructure.value?.pages.find((p) => p.id === page.id)
    if (sp) {
      sp.title = page.title
      sp.type = page.type
      sp.edited = page.edited
      sp.updated_at = page.updated_at
    }
  }

  function baseBody() {
    const r = effectiveRepoInfo.value
    return { owner: r.owner, repo: r.repo, repo_type: r.type, language: opts.language }
  }

  async function savePageEdit(pageId: string, content: string, title?: string) {
    pageBusy.value = pageId
    pageActionError.value = null
    try {
      const res = await $fetch<{ page: WikiPage }>('/api/wiki/page', {
        method: 'PUT',
        body: { ...baseBody(), page_id: pageId, content, title },
      })
      applyPageUpdate(res.page)
      return true
    } catch (err) {
      pageActionError.value = err instanceof Error ? err.message : '保存失败'
      return false
    } finally {
      pageBusy.value = null
    }
  }

  async function fetchPage(pageId: string): Promise<WikiPage | null> {
    const b = baseBody()
    const params = new URLSearchParams({
      owner: b.owner, repo: b.repo, repo_type: b.repo_type, language: b.language, page_id: pageId,
    })
    try {
      const res = await $fetch<{ page: WikiPage }>(`/api/wiki/page?${params.toString()}`)
      return res.page
    } catch {
      return null
    }
  }

  async function regeneratePage(pageId: string, instruction = '') {
    pageBusy.value = pageId
    pageActionError.value = null
    const prevUpdatedAt = generatedPages.value[pageId]?.updated_at || 0
    try {
      const r = effectiveRepoInfo.value
      const res = await $fetch<{ page: WikiPage }>('/api/wiki/page/regenerate', {
        method: 'POST',
        // Big pages (glossary + coverage repair) take ~5 min — longer than both this
        // timeout and the dev-proxy's ~300s limit. The backend keeps running after the
        // HTTP request dies, so on timeout we fall through to polling below.
        timeout: 270_000,
        body: {
          ...baseBody(),
          page_id: pageId,
          repo_url: r.repoUrl || '',
          token: r.token || '',
          provider: provider.value,
          model: model.value,
          instruction,
        },
      })
      applyPageUpdate(res.page)
      return true
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const status = (err as { statusCode?: number })?.statusCode
      const maybeStillRunning = /timeout|abort/i.test(msg) || status === 502 || status === 504
      if (!maybeStillRunning) {
        pageActionError.value = msg || '重新生成失败'
        return false
      }
      // Poll for the finished result (updated_at changes when the backend saves).
      for (let i = 0; i < 60; i++) { // up to ~10 min
        await new Promise((resolve) => setTimeout(resolve, 10_000))
        const p = await fetchPage(pageId)
        if (p && (p.updated_at || 0) > prevUpdatedAt) {
          applyPageUpdate(p)
          return true
        }
      }
      pageActionError.value = '生成时间过长：任务可能仍在后台运行，请稍后刷新页面查看'
      return false
    } finally {
      pageBusy.value = null
    }
  }

  async function revertPage(pageId: string, at?: number) {
    pageBusy.value = pageId
    pageActionError.value = null
    try {
      const res = await $fetch<{ page: WikiPage }>('/api/wiki/page/revert', {
        method: 'POST',
        body: { ...baseBody(), page_id: pageId, at },
      })
      applyPageUpdate(res.page)
      return true
    } catch (err) {
      pageActionError.value = err instanceof Error ? err.message : '回滚失败'
      return false
    } finally {
      pageBusy.value = null
    }
  }

  async function fetchPageHistory(pageId: string): Promise<HistoryEntry[]> {
    const b = baseBody()
    const params = new URLSearchParams({
      owner: b.owner, repo: b.repo, repo_type: b.repo_type, language: b.language, page_id: pageId,
    })
    const res = await $fetch<{ entries: HistoryEntry[] }>(`/api/wiki/page/history?${params.toString()}`)
    return res.entries || []
  }

  return {
    // state
    isLoading, loadingMessage, error, embeddingError,
    wikiStructure, currentPageId, generatedPages, pagesInProgress,
    effectiveRepoInfo, defaultBranch, isExporting, exportError, provider, model,
    pageBusy, pageActionError,
    // actions
    generateFileUrl, loadData, exportWiki, selectPage,
    savePageEdit, regeneratePage, revertPage, fetchPageHistory,
  }
}
