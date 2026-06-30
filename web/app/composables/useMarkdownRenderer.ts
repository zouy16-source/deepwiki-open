import MarkdownIt from 'markdown-it'
import type { Token } from 'markdown-it/index.js'
import { createHighlighter, type Highlighter } from 'shiki'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'
import markdownItKatexImport from '@vscode/markdown-it-katex'

// Ported from src/components/Markdown.tsx. Reproduces the react-markdown pipeline
// (remark-gfm + remark-math + rehype-raw + rehype-katex + react-syntax-highlighter)
// with markdown-it + shiki + katex, keeping the same per-element classes, the
// "Relevant source files" / inline-citation link resolution, and ```mermaid handling.

export type ResolveFileHref = (path: string) => string

export interface MarkdownSegment {
  type: 'markdown' | 'mermaid'
  /** raw markdown source (markdown segments) */
  src?: string
  /** mermaid chart body (mermaid segments) */
  chart?: string
}

// A bare repo file path: no scheme, not absolute/anchor/query, ending in a file
// extension — e.g. "nuxt.config.js" or "plugins/axios/index.js".
function isBareFilePath(href: string): boolean {
  if (!href) return false
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return false // has a scheme (http:, mailto:, …)
  if (/^[/#?]/.test(href)) return false // absolute path / anchor / query
  return /\.[a-z0-9]{1,8}(#.*)?$/i.test(href) // ends in a file extension
}

// Build a source URL from an inline citation's link text, e.g. "libs/menu.js:27-42"
// or "api/index.js:100" (emitted with an empty href, so we derive from the text).
function citationHref(text: string, resolve: ResolveFileHref): string | null {
  const t = text.trim()
  const m = t.match(/^(.+?\.[a-z0-9]{1,8}):(\d+)(?:-(\d+))?$/i)
  if (m) {
    const base = resolve(m[1])
    if (!base || base === m[1]) return null
    const anchor = base.includes('/-/blob/')
      ? `#L${m[2]}${m[3] ? `-${m[3]}` : ''}` // GitLab: #L27-42
      : `#L${m[2]}${m[3] ? `-L${m[3]}` : ''}` // GitHub/others: #L27-L42
    return base + anchor
  }
  if (isBareFilePath(t)) {
    const base = resolve(t)
    return base && base !== t ? base : null
  }
  return null
}

const COPY_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>'

// Languages preloaded into shiki. Unknown languages fall back to plain text.
const SHIKI_LANGS = [
  'text', 'javascript', 'typescript', 'jsx', 'tsx', 'vue', 'python', 'bash',
  'shell', 'json', 'jsonc', 'yaml', 'markdown', 'html', 'css', 'scss', 'go',
  'rust', 'java', 'kotlin', 'c', 'cpp', 'csharp', 'php', 'ruby', 'sql', 'toml',
  'ini', 'dockerfile', 'diff', 'xml',
]

function addClass(md: MarkdownIt, rule: string, cls: string) {
  const prev = md.renderer.rules[rule]
  md.renderer.rules[rule] = (tokens, idx, options, env, self) => {
    tokens[idx].attrJoin('class', cls)
    return prev ? prev(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options)
  }
}

function applyRules(md: MarkdownIt, highlighter: Highlighter, loadedLangs: Set<string>) {
  addClass(md, 'paragraph_open', 'mb-3 text-sm leading-relaxed dark:text-white')
  addClass(md, 'bullet_list_open', 'list-disc pl-6 mb-4 text-sm dark:text-white space-y-2')
  addClass(md, 'ordered_list_open', 'list-decimal pl-6 mb-4 text-sm dark:text-white space-y-2')
  addClass(md, 'list_item_open', 'mb-2 text-sm leading-relaxed dark:text-white')
  addClass(md, 'blockquote_open', 'border-l-4 border-gray-300 dark:border-gray-700 pl-4 py-1 text-gray-700 dark:text-gray-300 italic my-4 text-sm')
  addClass(md, 'thead_open', 'bg-gray-100 dark:bg-gray-800')
  addClass(md, 'tbody_open', 'divide-y divide-gray-200 dark:divide-gray-700')
  addClass(md, 'tr_open', 'hover:bg-gray-50 dark:hover:bg-gray-900')
  addClass(md, 'th_open', 'px-4 py-3 text-left font-medium text-gray-700 dark:text-gray-300')
  addClass(md, 'td_open', 'px-4 py-3 border-t border-gray-200 dark:border-gray-700')

  // Tables get an overflow wrapper (matches the React <div><table/></div>).
  md.renderer.rules.table_open = () =>
    '<div class="overflow-x-auto my-6 rounded-md"><table class="min-w-full text-sm border-collapse">'
  md.renderer.rules.table_close = () => '</table></div>'

  // Headings: per-level classes + special ReAct (Thought/Action/Observation/Answer) styling on h2.
  md.renderer.rules.heading_open = (tokens, idx, options, _env, self) => {
    const token = tokens[idx]
    const tag = token.tag
    const inline = tokens[idx + 1]
    const text = inline && inline.type === 'inline' ? inline.content : ''
    let cls: string
    if (tag === 'h1') {
      cls = 'text-xl font-bold mt-6 mb-3 dark:text-white'
    } else if (tag === 'h2') {
      if (/Thought|Action|Observation|Answer/.test(text)) {
        const base = 'text-base font-bold mt-5 mb-3 p-2 rounded '
        cls = base + (
          text.includes('Thought') ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300'
          : text.includes('Action') ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
          : text.includes('Observation') ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300'
          : text.includes('Answer') ? 'bg-teal-100 dark:bg-teal-900/30 text-teal-800 dark:text-teal-300'
          : 'dark:text-white'
        )
      } else {
        cls = 'text-lg font-bold mt-5 mb-3 dark:text-white'
      }
    } else if (tag === 'h3') {
      cls = 'text-base font-semibold mt-4 mb-2 dark:text-white'
    } else if (tag === 'h4') {
      cls = 'text-sm font-semibold mt-3 mb-2 dark:text-white'
    } else {
      cls = 'font-semibold dark:text-white'
    }
    token.attrJoin('class', cls)
    return self.renderToken(tokens, idx, options)
  }

  // Inline code.
  md.renderer.rules.code_inline = (tokens, idx) =>
    `<code class="font-mono bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-[var(--accent-secondary)] text-sm">${md.utils.escapeHtml(tokens[idx].content)}</code>`

  // Links: resolve "Relevant source files" bare paths and empty-href inline citations.
  md.renderer.rules.link_open = (tokens, idx, options, env: { resolveFileHref?: ResolveFileHref }, self) => {
    const token = tokens[idx]
    const href = token.attrGet('href') || ''
    const resolve = env?.resolveFileHref
    let finalHref = href
    if (resolve) {
      if (href && isBareFilePath(href)) {
        finalHref = resolve(href)
      } else if (!href) {
        let text = ''
        for (let i = idx + 1; i < tokens.length && tokens[i].type !== 'link_close'; i++) {
          text += tokens[i].content || ''
        }
        finalHref = citationHref(text, resolve) || href
      }
    }
    if (finalHref) token.attrSet('href', finalHref)
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
    token.attrJoin('class', 'text-[var(--link-color)] hover:underline font-medium')
    return self.renderToken(tokens, idx, options)
  }

  // Fenced code blocks: shiki dual-theme highlight, with a header (language label
  // + copy button) wrapper. Mermaid fences are normally split out before render;
  // this is a defensive fallback.
  md.renderer.rules.fence = (tokens: Token[], idx: number) => {
    const token = tokens[idx]
    const info = (token.info || '').trim()
    const lang = (info.split(/\s+/)[0] || 'text').toLowerCase()
    const code = token.content.replace(/\n$/, '')
    if (lang === 'mermaid') {
      return `<pre class="mermaid">${md.utils.escapeHtml(code)}</pre>`
    }
    const useLang = loadedLangs.has(lang) ? lang : 'text'
    let highlighted: string
    try {
      highlighted = highlighter.codeToHtml(code, {
        lang: useLang,
        themes: { light: 'github-light', dark: 'github-dark' },
        defaultColor: false,
      })
    } catch {
      highlighted = `<pre class="shiki"><code>${md.utils.escapeHtml(code)}</code></pre>`
    }
    const label = md.utils.escapeHtml(info || 'text')
    return (
      '<div class="code-block my-6 rounded-md overflow-hidden text-sm shadow-sm">' +
      '<div class="code-block-header">' +
      `<span>${label}</span>` +
      `<button class="copy-btn" type="button" title="Copy code" aria-label="Copy code">${COPY_SVG}</button>` +
      '</div>' +
      highlighted +
      '</div>'
    )
  }
}

let mdPromise: Promise<MarkdownIt> | null = null

async function build(): Promise<MarkdownIt> {
  const highlighter = await createHighlighter({
    themes: ['github-light', 'github-dark'],
    langs: SHIKI_LANGS,
    engine: createJavaScriptRegexEngine({ forgiving: true }),
  })
  const loadedLangs = new Set(highlighter.getLoadedLanguages())

  const md = new MarkdownIt({
    html: true, // rehype-raw equivalent
    linkify: true, // remark-gfm autolinks
    breaks: false,
    typographer: false,
  })

  // remark-math + rehype-katex equivalent. The plugin's interop default export.
  const katexPlugin = (markdownItKatexImport as unknown as { default?: MarkdownIt.PluginSimple }).default
    ?? (markdownItKatexImport as unknown as MarkdownIt.PluginSimple)
  md.use(katexPlugin)

  applyRules(md, highlighter, loadedLangs)
  return md
}

/** Singleton markdown-it instance (shiki highlighter is expensive to build). */
export function getMarkdownIt(): Promise<MarkdownIt> {
  if (!mdPromise) mdPromise = build()
  return mdPromise
}

/**
 * Split markdown into ordered segments, pulling ```mermaid fences out as their own
 * segments (rendered by the <Mermaid> Vue component, since they need async render,
 * a fullscreen modal and pan-zoom — none of which fit an HTML string).
 */
export function splitMarkdownSegments(md: MarkdownIt, content: string): MarkdownSegment[] {
  const text = content || ''
  const tokens = md.parse(text, {})
  const lines = text.split('\n')
  const segs: MarkdownSegment[] = []
  let cursor = 0

  for (const t of tokens) {
    if (t.type === 'fence' && t.map && (t.info || '').trim().toLowerCase() === 'mermaid') {
      const [start, end] = t.map
      if (start > cursor) {
        const src = lines.slice(cursor, start).join('\n')
        if (src.trim()) segs.push({ type: 'markdown', src })
      }
      segs.push({ type: 'mermaid', chart: t.content })
      cursor = end
    }
  }
  if (cursor < lines.length) {
    const src = lines.slice(cursor).join('\n')
    if (src.trim()) segs.push({ type: 'markdown', src })
  }
  if (segs.length === 0) segs.push({ type: 'markdown', src: text })
  return segs
}
