<script setup lang="ts">
// 对话式创建需求：左侧与项目代码库 AI 问答（agentic 通道：每轮先 grep/read_file
// 工具循环查证再回答，引用经机器核验——RAG 语义检索对精确标识符失效，见 consigneeArea 事件），
// 右侧需求草稿实时预览（每轮回答后自动重提取；手动编辑后暂停覆盖）。
// 创建时对话快照随需求落库（source_context），作为后续 AI 可行性分析的种子线索。
import type { Project, Requirement } from '~/types/requirement'

definePageMeta({ layout: 'home' })

const toast = useToast()

// ---- 项目与仓库 ----
const { data: projects } = useFetch<Project[]>('/api/projects', { default: () => [] })
const projectId = ref<number | null>(null)
watch(projects, (ps) => {
  if (ps?.length && projectId.value === null) projectId.value = ps[0]!.id
}, { immediate: true })
const project = computed(() => projects.value?.find(p => p.id === projectId.value) || null)
const projectItems = computed(() => (projects.value || []).map(p => ({ label: p.name, value: p.id })))

const repoName = ref('')
watch(project, (p) => { repoName.value = p?.repos?.[0] || '' }, { immediate: true })
const repoItems = computed(() => (project.value?.repos || []).map(r => ({ label: r, value: r })))

// ---- 对话（agentic SSE：step 进度 + answer 终答）----
interface ChatStep { tool: string, args: string, result: string }
interface Msg {
  role: 'user' | 'assistant'
  content: string
  steps?: ChatStep[]
  citesOk?: number
  citesBad?: number
  toolCalls?: number
}
const messages = ref<Msg[]>([])
const input = ref('')
const chatting = ref(false)
const chatBox = ref<HTMLElement | null>(null)

function scrollChat() {
  nextTick(() => chatBox.value?.scrollTo({ top: chatBox.value.scrollHeight }))
}

function patchLast(patch: Partial<Msg>) {
  const arr = [...messages.value]
  const last = arr[arr.length - 1]!
  arr[arr.length - 1] = { ...last, ...patch }
  messages.value = arr
  scrollChat()
}

async function consumeSse(resp: Response, onEvent: (ev: any) => void) {
  const reader = resp.body!.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = chunk.split('\n').find(l => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

async function send() {
  const q = input.value.trim()
  if (!q || chatting.value) return
  if (!repoName.value) {
    toast.add({ title: '当前项目未绑定代码库', description: '请先在项目空间绑定仓库（repos）', color: 'warning' })
    return
  }
  input.value = ''
  const history = [...messages.value.filter(m => m.content), { role: 'user' as const, content: q }]
  messages.value = [...messages.value, { role: 'user', content: q }, { role: 'assistant', content: '', steps: [] }]
  chatting.value = true
  scrollChat()

  try {
    const resp = await fetch('/api/chat/agentic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: repoName.value, messages: history.map(m => ({ role: m.role, content: m.content })) }),
    })
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
    await consumeSse(resp, (ev) => {
      if (ev.type === 'step') {
        const last = messages.value[messages.value.length - 1]!
        patchLast({ steps: [...(last.steps || []), ev as ChatStep] })
      } else if (ev.type === 'answer') {
        patchLast({ content: ev.content, citesOk: ev.cites_ok, citesBad: ev.cites_bad, toolCalls: ev.tool_calls })
      } else if (ev.type === 'error') {
        patchLast({ content: `出错：${ev.message}` })
      }
    })
    refreshDraft() // 每轮回答完成后自动更新草稿
  } catch (e) {
    patchLast({ content: `出错：${e instanceof Error ? e.message : '未知错误'}` })
  } finally {
    chatting.value = false
  }
}

// ---- 需求草稿（右侧实时预览）----
const draft = reactive({
  title: '',
  req_type: 'business' as 'business' | 'system',
  priority: 'P1' as 'P0' | 'P1' | 'P2',
  description: '',
  gaps: [] as string[],
})
const drafting = ref(false)
const dirty = ref(false) // 手动编辑后暂停自动覆盖
const hasDraft = computed(() => !!draft.title || !!draft.description)

async function refreshDraft(force = false) {
  const rounds = messages.value.filter(m => m.content).length
  if (rounds < 2 || drafting.value) return
  if (dirty.value && !force) return
  drafting.value = true
  try {
    const data = await $fetch<typeof draft>('/api/analysis/draft', {
      method: 'POST',
      body: { messages: messages.value.filter(m => m.content), project_name: project.value?.name || '' },
    })
    Object.assign(draft, data)
    if (force) dirty.value = false
  } catch (e: any) {
    toast.add({ title: '草稿生成失败', description: e?.data?.detail || e?.statusMessage || '可稍后手动重新生成', color: 'warning' })
  } finally {
    drafting.value = false
  }
}

// ---- 创建需求 ----
const creating = ref(false)
async function createRequirement() {
  if (!projectId.value || !draft.title.trim() || creating.value) return
  creating.value = true
  try {
    const transcript = messages.value
      .filter(m => m.content)
      .map(m => `[${m.role === 'user' ? '产品' : 'AI'}] ${m.content}`)
      .join('\n\n')
      .slice(0, 12000)
    const created = await $fetch<Requirement>('/api/requirements', {
      method: 'POST',
      body: {
        project_id: projectId.value,
        req_type: draft.req_type,
        title: draft.title.trim(),
        description: draft.description,
        priority: draft.priority,
        source_context: transcript,
      },
    })
    toast.add({ title: `需求 #${created.id} 已创建`, description: '对话已作为产物绑定，可提交 AI 分析', color: 'success' })
    await navigateTo(`/requirements/${created.id}`)
  } catch (e: any) {
    toast.add({ title: '创建失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="h-full overflow-hidden flex flex-col">
    <div class="flex flex-wrap items-center gap-3 p-3 border-b border-default">
      <UButton variant="ghost" color="neutral" icon="i-lucide-arrow-left" size="sm" to="/requirements" />
      <span class="font-medium text-highlighted">对话创建需求</span>
      <USelect v-model="projectId" :items="projectItems" class="w-44" size="sm" :disabled="messages.length > 0" />
      <USelect v-if="repoItems.length > 1" v-model="repoName" :items="repoItems" class="w-56" size="sm" />
      <UBadge v-else-if="repoName" :label="repoName" color="neutral" variant="outline" size="sm" />
      <UAlert
        v-if="project && !repoName"
        color="warning"
        variant="subtle"
        icon="i-lucide-circle-alert"
        title="当前项目未绑定代码库，AI 无法回答代码问题"
        class="flex-1 py-1"
      />
    </div>

    <div class="flex-1 grid grid-cols-1 lg:grid-cols-2 min-h-0">
      <!-- 左：对话 -->
      <div class="flex flex-col min-h-0 border-r border-default">
        <div ref="chatBox" class="flex-1 overflow-y-auto overflow-x-hidden p-4 space-y-4">
          <div v-if="!messages.length" class="text-center text-muted pt-16 space-y-2">
            <UIcon name="i-lucide-messages-square" class="size-10 opacity-50" />
            <p class="text-sm">先和代码库 AI 聊清楚：现有逻辑是什么样、想改成什么样。</p>
            <p class="text-xs">例：「运单导出现在是怎么实现的？」「如果要支持按客户批量导出，现有代码能撑住吗？」</p>
          </div>
          <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : ''">
            <div
              class="chat-bubble max-w-[85%] min-w-0 rounded-lg px-3 py-2 text-sm"
              :class="m.role === 'user' ? 'bg-primary text-inverted' : 'bg-elevated/60'"
            >
              <template v-if="m.role === 'assistant' && m.content">
                <Markdown :content="m.content" />
                <p v-if="m.toolCalls" class="mt-2 pt-1.5 border-t border-default/60 text-xs text-muted flex items-center gap-1.5">
                  <UIcon name="i-lucide-search-code" class="size-3.5" />
                  代码检索 {{ m.toolCalls }} 次
                  <template v-if="(m.citesOk || 0) + (m.citesBad || 0) > 0">
                    · 引用核验 {{ m.citesOk }} 通过<template v-if="m.citesBad"> / <span class="text-warning">{{ m.citesBad }} 未通过</span></template>
                  </template>
                </p>
              </template>
              <div v-else-if="m.role === 'assistant'" class="space-y-1 text-muted">
                <span class="inline-flex items-center gap-1.5">
                  <UIcon name="i-lucide-loader-circle" class="size-3.5 animate-spin" />
                  {{ m.steps?.length ? '正在检索代码…' : '思考中…' }}
                </span>
                <div v-if="m.steps?.length" class="text-xs font-mono space-y-0.5 max-h-32 overflow-y-auto">
                  <p v-for="(s, si) in m.steps" :key="si" class="truncate">
                    <span class="text-primary">{{ s.tool }}</span> {{ s.args }} <span class="text-dimmed">→ {{ s.result }}</span>
                  </p>
                </div>
              </div>
              <span v-else class="whitespace-pre-wrap">{{ m.content }}</span>
            </div>
          </div>
        </div>
        <div class="p-3 border-t border-default flex gap-2">
          <UTextarea
            v-model="input"
            :rows="2"
            autoresize
            :maxrows="5"
            placeholder="询问代码逻辑、业务可行性…（Enter 发送，Shift+Enter 换行）"
            class="flex-1"
            @keydown.enter.exact.prevent="send"
          />
          <UButton icon="i-lucide-send" :loading="chatting" :disabled="!input.trim()" @click="send">对话</UButton>
        </div>
      </div>

      <!-- 右：需求草稿实时预览 -->
      <div class="flex flex-col min-h-0">
        <div class="flex items-center gap-2 p-3 border-b border-default">
          <UIcon name="i-lucide-file-pen-line" class="size-4 text-primary" />
          <span class="text-sm font-medium text-highlighted">需求草稿</span>
          <UBadge v-if="drafting" label="生成中…" color="primary" variant="subtle" size="sm" />
          <UBadge v-else-if="dirty" label="已手动编辑，自动更新已暂停" color="warning" variant="subtle" size="sm" />
          <UButton
            variant="ghost"
            color="neutral"
            size="xs"
            icon="i-lucide-refresh-cw"
            class="ml-auto"
            :disabled="messages.filter(m => m.content).length < 2 || drafting"
            @click="refreshDraft(true)"
          >
            重新生成
          </UButton>
        </div>

        <div class="flex-1 overflow-y-auto p-4 space-y-4">
          <p v-if="!hasDraft" class="text-sm text-muted pt-16 text-center">
            聊几轮后，这里会自动生成需求草稿（AI 起草，创建前请核对）。
          </p>
          <template v-else>
            <UFormField label="需求标题" required>
              <UInput v-model="draft.title" maxlength="255" class="w-full" @input="dirty = true" />
            </UFormField>
            <div class="grid grid-cols-2 gap-3">
              <UFormField label="类型">
                <USelect
                  v-model="draft.req_type"
                  :items="[{ label: '业务需求', value: 'business' }, { label: '系统需求', value: 'system' }]"
                  class="w-full"
                  @update:model-value="dirty = true"
                />
              </UFormField>
              <UFormField label="优先级">
                <USelect
                  v-model="draft.priority"
                  :items="[{ label: 'P0 — 必须', value: 'P0' }, { label: 'P1 — 重要', value: 'P1' }, { label: 'P2 — 一般', value: 'P2' }]"
                  class="w-full"
                  @update:model-value="dirty = true"
                />
              </UFormField>
            </div>
            <UFormField label="需求描述">
              <UTextarea v-model="draft.description" :rows="12" class="w-full font-mono text-xs" @input="dirty = true" />
            </UFormField>
            <UAlert
              v-if="draft.gaps.length"
              color="warning"
              variant="subtle"
              icon="i-lucide-list-todo"
              title="创建前建议补充确认"
            >
              <template #description>
                <ul class="list-disc list-inside space-y-0.5">
                  <li v-for="g in draft.gaps" :key="g">{{ g }}</li>
                </ul>
              </template>
            </UAlert>
          </template>
        </div>

        <div class="p-3 border-t border-default flex items-center gap-2">
          <p class="text-xs text-muted flex-1">创建后对话将作为产物绑定需求，并作为 AI 分析的种子线索</p>
          <UButton
            icon="i-lucide-check"
            :loading="creating"
            :disabled="!draft.title.trim() || !projectId"
            @click="createRequirement"
          >
            创建需求
          </UButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 长路径/标识符等无断点字符串：允许任意处断行，杜绝气泡横向溢出 */
.chat-bubble {
  overflow-wrap: anywhere;
}

/* markdown 渲染器给行内 code 加了 inline-block，长路径不换行会撑破气泡：限宽 + 任意断行 */
.chat-bubble :deep(code) {
  max-width: 100%;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 代码块在自身内部横向滚动，不撑宽气泡；块内代码保持原样不强制断行 */
.chat-bubble :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
}

.chat-bubble :deep(pre code) {
  white-space: pre;
  word-break: normal;
}

/* markdown 表格同理：自身横滚 */
.chat-bubble :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
</style>
