<script setup lang="ts">
// Simplified port of src/components/Ask.tsx for the docked input-only mode used by
// the wiki page (hideModelSelection + hideDeepResearch). Q&A over the chat stream.
import type { RepoInfo } from '~/types/wiki'

const props = defineProps<{
  repoInfo: RepoInfo
  provider: string
  model: string
  isCustomModel?: boolean
  customModel?: string
  language: string
}>()

const { t } = useI18n()
const baseUrl = (useRuntimeConfig().public.serverBaseUrl as string) || 'http://localhost:8001'

interface Msg { role: 'user' | 'assistant'; content: string }
const history = ref<Msg[]>([])
const input = ref('')
const loading = ref(false)

async function ask() {
  const q = input.value.trim()
  if (!q || loading.value) return
  input.value = ''
  history.value = [...history.value, { role: 'user', content: q }, { role: 'assistant', content: '' }]
  loading.value = true

  const reqMessages = history.value
    .filter((m) => !(m.role === 'assistant' && m.content === ''))
    .map((m) => ({ role: m.role, content: m.content }))

  const body: ChatStreamRequest = {
    repo_url: getRepoUrl(props.repoInfo),
    type: props.repoInfo.type,
    messages: reqMessages,
  }
  addTokensToRequestBody(body, {
    token: props.repoInfo.token || '',
    provider: props.provider,
    model: props.model,
    isCustomModel: props.isCustomModel,
    customModel: props.customModel,
    language: props.language,
  })

  function setLast(content: string) {
    const arr = [...history.value]
    arr[arr.length - 1] = { role: 'assistant', content }
    history.value = arr
  }

  try {
    await streamChat(baseUrl, body, setLast)
  } catch (e) {
    setLast(`出错: ${e instanceof Error ? e.message : '未知错误'}`)
  } finally {
    loading.value = false
  }
}

function clearConversation() {
  history.value = []
}
defineExpose({ clearConversation })
</script>

<template>
  <div class="flex flex-col">
    <div v-if="history.length" class="max-h-72 overflow-y-auto px-4 pt-3 space-y-3 border-b border-[var(--border-color)]">
      <div v-for="(m, i) in history" :key="i">
        <div v-if="m.role === 'user'" class="text-sm font-medium text-[var(--accent-primary)]">
          {{ m.content }}
        </div>
        <div v-else class="text-sm">
          <span v-if="!m.content" class="text-[var(--muted)]">…</span>
          <Suspense v-else>
            <Markdown :content="m.content" />
            <template #fallback><span class="text-[var(--muted)]">…</span></template>
          </Suspense>
        </div>
      </div>
    </div>

    <form class="flex items-end gap-2 p-3" @submit.prevent="ask">
      <UTextarea
        v-model="input"
        :rows="1"
        autoresize
        :placeholder="t('ask.placeholder')"
        :disabled="loading"
        class="flex-1"
        :ui="{ root: 'w-full' }"
        @keydown.enter.exact.prevent="ask"
      />
      <UButton
        type="submit"
        color="primary"
        icon="i-fa6-solid-paper-plane"
        :loading="loading"
        :label="t('ask.askButton')"
      />
      <UButton
        v-if="history.length"
        color="neutral"
        variant="ghost"
        icon="i-fa6-solid-trash"
        square
        :disabled="loading"
        :aria-label="t('common.close')"
        @click="clearConversation"
      />
    </form>
  </div>
</template>
