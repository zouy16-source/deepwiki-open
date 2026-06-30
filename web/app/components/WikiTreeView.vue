<script setup lang="ts">
// Ported from src/components/WikiTreeView.tsx. Tree (sections) or flat fallback.
import type { WikiStructure } from '~/types/wiki'

const props = defineProps<{
  wikiStructure: WikiStructure
  currentPageId?: string
}>()
const emit = defineEmits<{ pageSelect: [id: string] }>()

const expanded = ref<Set<string>>(new Set(props.wikiStructure.rootSections))

function toggle(id: string) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}
function select(id: string) {
  emit('pageSelect', id)
}

const isFlat = computed(
  () =>
    !props.wikiStructure.sections?.length ||
    !props.wikiStructure.rootSections?.length,
)

function dotClass(importance: string) {
  return importance === 'high'
    ? 'bg-primary'
    : importance === 'medium'
      ? 'bg-secondary'
      : 'bg-error'
}
</script>

<template>
  <ul v-if="isFlat" class="space-y-2">
    <li v-for="page in wikiStructure.pages" :key="page.id">
      <button
        class="w-full text-left px-3 py-2 rounded-md text-sm transition-colors"
        :class="currentPageId === page.id
          ? 'bg-primary/20 text-primary border border-primary/30'
          : 'text-default hover:bg-default border border-transparent'"
        @click="select(page.id)"
      >
        <div class="flex items-center">
          <div class="w-2 h-2 rounded-full mr-2 flex-shrink-0" :class="dotClass(page.importance)" />
          <span class="truncate">{{ page.title }}</span>
        </div>
      </button>
    </li>
  </ul>

  <div v-else class="space-y-1">
    <WikiTreeSection
      v-for="id in wikiStructure.rootSections"
      :key="id"
      :section-id="id"
      :level="0"
      :wiki-structure="wikiStructure"
      :current-page-id="currentPageId"
      :expanded="expanded"
      :toggle="toggle"
      :select="select"
    />
  </div>
</template>
