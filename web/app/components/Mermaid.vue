<script setup lang="ts">
import type mermaidType from 'mermaid'

// Ported from src/components/Mermaid.tsx. Renders a mermaid chart to SVG, with a
// click-to-fullscreen modal (wheel/buttons zoom) and optional svg-pan-zoom.

const props = withDefaults(defineProps<{
  chart: string
  className?: string
  zoomingEnabled?: boolean
}>(), {
  className: '',
  zoomingEnabled: false,
})

const THEME_CSS = `
    /* Japanese aesthetic styles for all diagrams */
    .node rect, .node circle, .node ellipse, .node polygon, .node path {
      fill: #f8f4e6;
      stroke: var(--ui-secondary);
      stroke-width: 1px;
    }
    .edgePath .path { stroke: var(--ui-primary); stroke-width: 1.5px; }
    .edgeLabel { background-color: transparent; color: #333333; p { background-color: transparent !important; } }
    .label { color: #333333; }
    .cluster rect { fill: #f8f4e6; stroke: var(--ui-secondary); stroke-width: 1px; }

    /* Sequence diagram specific styles */
    .actor { fill: #f8f4e6; stroke: var(--ui-secondary); stroke-width: 1px; }
    text.actor { fill: #333333; stroke: none; }
    .messageText { fill: #333333; stroke: none; }
    .messageLine0, .messageLine1 { stroke: var(--ui-primary); }
    .noteText { fill: #333333; }

    /* Dark mode overrides - applied when the rendered <svg> carries data-theme="dark" */
    [data-theme="dark"] .node rect, [data-theme="dark"] .node circle, [data-theme="dark"] .node ellipse,
    [data-theme="dark"] .node polygon, [data-theme="dark"] .node path { fill: #222222; stroke: #5d4037; }
    [data-theme="dark"] .edgePath .path { stroke: var(--ui-primary); }
    [data-theme="dark"] .edgeLabel { background-color: transparent; color: #f0f0f0; }
    [data-theme="dark"] .label { color: #f0f0f0; }
    [data-theme="dark"] .cluster rect { fill: #222222; stroke: #5d4037; }
    [data-theme="dark"] .flowchart-link { stroke: var(--ui-primary); }

    [data-theme="dark"] .actor { fill: #222222; stroke: #5d4037; }
    [data-theme="dark"] text.actor { fill: #f0f0f0; stroke: none; }
    [data-theme="dark"] .messageText { fill: #f0f0f0; stroke: none; font-weight: 500; }
    [data-theme="dark"] .messageLine0, [data-theme="dark"] .messageLine1 { stroke: var(--ui-primary); stroke-width: 1.5px; }
    [data-theme="dark"] .noteText { fill: #f0f0f0; }
    [data-theme="dark"] #sequenceNumber { fill: #f0f0f0; }
    [data-theme="dark"] text.sequenceText { fill: #f0f0f0; font-weight: 500; }
    [data-theme="dark"] text.loopText, [data-theme="dark"] text.loopText tspan { fill: #f0f0f0; }
    [data-theme="dark"] .messageText, [data-theme="dark"] text.sequenceText {
      paint-order: stroke; stroke: #1a1a1a; stroke-width: 2px; stroke-linecap: round; stroke-linejoin: round;
    }

    /* Force text elements to be properly colored */
    text[text-anchor][dominant-baseline], text[text-anchor][alignment-baseline],
    .nodeLabel, .edgeLabel, .label, text { fill: #777 !important; }
    [data-theme="dark"] text[text-anchor][dominant-baseline], [data-theme="dark"] text[text-anchor][alignment-baseline],
    [data-theme="dark"] .nodeLabel, [data-theme="dark"] .edgeLabel, [data-theme="dark"] .label,
    [data-theme="dark"] text { fill: #f0f0f0 !important; }

    .clickable { transition: all 0.3s ease; }
    .clickable:hover { transform: scale(1.03); cursor: pointer; }
    .clickable:hover > * { filter: brightness(0.95); }
`

// Initialize mermaid exactly once, lazily, on the client.
let mermaidReady: Promise<typeof mermaidType> | null = null
function ensureMermaid(): Promise<typeof mermaidType> {
  if (!mermaidReady) {
    mermaidReady = import('mermaid').then((m) => {
      const mermaid = m.default
      mermaid.initialize({
        startOnLoad: false,
        theme: 'neutral',
        securityLevel: 'loose',
        suppressErrorRendering: true,
        logLevel: 'error',
        maxTextSize: 100000,
        htmlLabels: true,
        flowchart: { htmlLabels: true, curve: 'basis', nodeSpacing: 60, rankSpacing: 60, padding: 20 },
        themeCSS: THEME_CSS,
        fontFamily: 'var(--font-geist-sans), var(--), sans-serif',
        fontSize: 12,
      })
      return mermaid
    })
  }
  return mermaidReady
}

// LLMs markdown-escape punctuation inside diagram text (e.g. "goAuthLogin\(\)", "\_",
// "\."). Mermaid has no backslash escaping, so these render as stray backslashes or —
// once a label is quoted below — inject characters that break the parse. Drop the
// backslash before punctuation that is safe to bare; deliberately NOT [ ] | " ` since
// those would collide with the label/quote structure quoteSpecialLabels relies on.
function unescapeMarkdownPunct(src: string): string {
  return src.replace(/\\([!#$%&'()*+,\-.\/:;<=>?@\\^_{}~])/g, '$1')
}

// Quote node/edge labels that contain '@' (e.g. "@nuxtjs/axios", decorators).
// LLM-generated diagrams routinely put characters Mermaid v11 rejects in unquoted
// labels — '@' (node-metadata syntax), and in edge/node labels things like
// '(' ':' '/' "'" (e.g. |request(url: '/x')| or [Key: Value]). Quote any label that
// holds a char beyond word/space and a few tolerated marks (. , -). Already-quoted
// labels are left untouched.
function quoteSpecialLabels(src: string): string {
  // \x00 (mask byte, below) counts as safe so masked labels aren't re-quoted.
  const UNSAFE = /[^\w\s.,\-\x00]/
  const masks: string[] = []
  const mask = (s: string) => `\x00${masks.push(s) - 1}\x00`
  // 0) Mask pre-existing quoted strings so the passes below never reach inside them.
  let s = src.replace(/"[^"\n]*"/g, mask)
  // 1) Edge (pipe) labels: quote the whole |...| label when unsafe, then mask the
  //    quoted text so its punctuation can't be re-matched by a node-shape pass below.
  s = s.replace(/(\|)([^"\n|]+?)(\|)/g, (m, o, l, c) =>
    UNSAFE.test(l) ? `${o}${mask(`"${l}"`)}${c}` : m)
  // 2) Node labels: [rect], (round), {diamond}. Quote when unsafe and mask each result
  //    BEFORE the next pass runs — otherwise nested punctuation in a just-quoted label
  //    (e.g. the parens inside [ ... goAuthLogin() ... ]) gets matched again by a later
  //    pass and corrupted with injected quotes.
  const shape = (re: RegExp) => {
    s = s.replace(re, (_m: string, o: string, l: string, c: string) =>
      UNSAFE.test(l) ? `${o}${mask(`"${l}"`)}${c}` : `${o}${l}${c}`)
  }
  shape(/(\[)([^[\]"\n|]+?)(\])/g) // [label]
  shape(/(\()([^()"\n|]+?)(\))/g) // (label)
  shape(/(\{)([^{}"\n|]+?)(\})/g) // {label}
  // 3) Restore masked strings.
  return s.replace(/\x00(\d+)\x00/g, (_m, i) => masks[Number(i)] ?? _m)
}

// Strip artifacts the LLM sometimes appends inside a ```mermaid block (e.g. a
// trailing "Sources: [file](...)" citation line), unescape markdown punctuation, then
// quote labels with special characters — all break or dirty Mermaid parsing.
function cleanMermaidChart(raw: string): string {
  const lines = (raw || '').split('\n')
  const out: string[] = []
  for (const line of lines) {
    if (/^\s*sources?\s*[:：]/i.test(line)) break
    out.push(line)
  }
  return quoteSpecialLabels(unescapeMarkdownPunct(out.join('\n').trim()))
}

const colorMode = useColorMode()
const svg = ref('')
const error = ref<string | null>(null)
const isFullscreen = ref(false)
const containerRef = ref<HTMLDivElement | null>(null)
const id = `mermaid-${Math.random().toString(36).substring(2, 9)}`

const ZOOM_MIN = 0.5
const ZOOM_MAX = 5
const zoom = ref(1)

async function renderChart() {
  if (!props.chart) return
  try {
    error.value = null
    svg.value = ''
    const mermaid = await ensureMermaid()
    const cleaned = cleanMermaidChart(props.chart)
    const { svg: rendered } = await mermaid.render(id, cleaned)
    // Tag the SVG so the dark-mode themeCSS rules apply.
    svg.value = colorMode.value === 'dark'
      ? rendered.replace('<svg ', '<svg data-theme="dark" ')
      : rendered
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    error.value = `Failed to render diagram: ${message}`
    // eslint-disable-next-line no-console
    console.error('Mermaid rendering error:', err)
  }
}

// Pan-zoom (inline mode only): attach svg-pan-zoom once the SVG is in the DOM.
async function initPanZoom() {
  if (!props.zoomingEnabled || !svg.value || !containerRef.value) return
  await nextTick()
  const svgElement = containerRef.value.querySelector('svg')
  if (!svgElement) return
  svgElement.style.maxWidth = 'none'
  svgElement.style.width = '100%'
  svgElement.style.height = '100%'
  try {
    const svgPanZoom = (await import('svg-pan-zoom')).default
    svgPanZoom(svgElement, {
      zoomEnabled: true,
      controlIconsEnabled: true,
      fit: true,
      center: true,
      minZoom: 0.1,
      maxZoom: 10,
      zoomScaleSensitivity: 0.3,
    })
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('Failed to load svg-pan-zoom:', e)
  }
}

onMounted(() => {
  // Re-render on chart or theme change (theme flips the injected data-theme attr).
  watch(() => [props.chart, colorMode.value], renderChart, { immediate: true })
  watch(svg, () => { if (props.zoomingEnabled) setTimeout(() => void initPanZoom(), 100) })

  // Esc closes the fullscreen modal.
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') isFullscreen.value = false }
  window.addEventListener('keydown', onKey)
  onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
})

watch(isFullscreen, (open) => { if (open) zoom.value = 1 })

function openFullscreen() {
  if (!error.value && svg.value && !props.zoomingEnabled) isFullscreen.value = true
}
function zoomIn() { zoom.value = Math.min(ZOOM_MAX, Math.round((zoom.value + 0.1) * 100) / 100) }
function zoomOut() { zoom.value = Math.max(ZOOM_MIN, Math.round((zoom.value - 0.1) * 100) / 100) }
function zoomReset() { zoom.value = 1 }
function onWheel(e: WheelEvent) {
  const next = zoom.value - e.deltaY * 0.0015
  zoom.value = Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)) * 100) / 100
}
</script>

<template>
  <!-- Error state -->
  <div
    v-if="error"
    :class="`border border-error/30 rounded-md p-4 bg-error/5 ${className}`"
  >
    <div class="flex items-center mb-3">
      <div class="text-error text-xs font-medium flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        图表渲染错误
      </div>
    </div>
    <pre class="text-xs overflow-auto p-2 bg-gray-100 dark:bg-gray-800 rounded">{{ props.chart }}</pre>
    <div class="mt-3 text-xs text-muted">图表存在语法错误，无法渲染。</div>
  </div>

  <!-- Loading state -->
  <div v-else-if="!svg" :class="`flex justify-center items-center p-4 ${className}`">
    <div class="flex items-center space-x-2">
      <div class="w-2 h-2 bg-[var(--ui-primary)]/70 rounded-full animate-pulse" />
      <div class="w-2 h-2 bg-[var(--ui-primary)]/70 rounded-full animate-pulse delay-75" />
      <div class="w-2 h-2 bg-[var(--ui-primary)]/70 rounded-full animate-pulse delay-150" />
      <span class="text-muted text-xs ml-2">图表渲染中...</span>
    </div>
  </div>

  <!-- Rendered diagram -->
  <template v-else>
    <div ref="containerRef" :class="`w-full max-w-full ${zoomingEnabled ? 'h-[600px] p-4' : ''}`">
      <div :class="`relative group ${zoomingEnabled ? 'h-full rounded-lg border-2 border-black' : ''}`">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div
          :class="`flex justify-center overflow-auto text-center hover:shadow-md transition-shadow duration-200 rounded-md ${className} ${zoomingEnabled ? 'h-full' : 'cursor-zoom-in'}`"
          :title="zoomingEnabled ? undefined : '点击查看大图'"
          @click="openFullscreen"
          v-html="svg"
        />
        <div
          v-if="!zoomingEnabled"
          class="absolute top-2 right-2 bg-gray-700/70 dark:bg-gray-900/70 text-white p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center gap-1.5 text-xs shadow-md pointer-events-none"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            <line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" />
          </svg>
          <span>点击放大</span>
        </div>
      </div>
    </div>

    <!-- Fullscreen modal -->
    <Teleport to="body">
      <div
        v-if="isFullscreen && !zoomingEnabled"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
        @click.self="isFullscreen = false"
      >
        <div class="bg-elevated rounded-lg shadow-lg w-[95vw] max-w-[1600px] h-[90vh] overflow-hidden flex flex-col bg-elevated">
          <div class="flex items-center justify-between p-4 border-b border-default">
            <div class="flex items-center gap-2 font-medium text-default">
              图表
              <span class="text-xs font-normal text-muted">（滚动鼠标滚轮可缩放）</span>
            </div>
            <div class="flex items-center gap-4">
              <div class="flex items-center gap-2">
                <button class="text-default hover:bg-[var(--ui-primary)]/10 p-2 rounded-md border border-default transition-colors" aria-label="Zoom out" @click="zoomOut">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" />
                  </svg>
                </button>
                <span class="text-sm text-muted">{{ Math.round(zoom * 100) }}%</span>
                <button class="text-default hover:bg-[var(--ui-primary)]/10 p-2 rounded-md border border-default transition-colors" aria-label="Zoom in" @click="zoomIn">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" />
                  </svg>
                </button>
                <button class="text-default hover:bg-[var(--ui-primary)]/10 p-2 rounded-md border border-default transition-colors" aria-label="Reset zoom" @click="zoomReset">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" />
                  </svg>
                </button>
              </div>
              <button class="text-default hover:bg-[var(--ui-primary)]/10 p-2 rounded-md border border-default transition-colors" aria-label="Close" @click="isFullscreen = false">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>
          <div class="overflow-auto p-6 flex-1 flex items-center justify-center bg-default/50" @wheel.prevent="onWheel">
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div
              class="w-full h-full flex items-center justify-center [&>svg]:!w-full [&>svg]:!h-full [&>svg]:!max-w-full [&>svg]:!max-h-full"
              :style="{ transform: `scale(${zoom})`, transformOrigin: 'center center', transition: 'transform 0.1s ease-out' }"
              v-html="svg"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </template>
</template>
