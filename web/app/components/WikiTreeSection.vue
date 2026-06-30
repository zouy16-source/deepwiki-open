<script setup lang="ts">
// Recursive section node for WikiTreeView (renders pages + nested subsections).
import type { WikiStructure } from '~/types/wiki'

const props = defineProps<{
  sectionId: string
  level: number
  wikiStructure: WikiStructure
  currentPageId?: string
  expanded: Set<string>
  toggle: (id: string) => void
  select: (id: string) => void
}>()

const section = computed(() => props.wikiStructure.sections.find((s) => s.id === props.sectionId))
const isExpanded = computed(() => props.expanded.has(props.sectionId))

function pageFor(id: string) {
  return props.wikiStructure.pages.find((p) => p.id === id)
}
function dotClass(importance: string) {
  return importance === 'high'
    ? 'bg-[var(--accent-primary)]'
    : importance === 'medium'
      ? 'bg-[var(--accent-secondary)]'
      : 'bg-[var(--highlight)]'
}
</script>

<template>
  <div v-if="section" class="mb-2">
    <button
      class="flex items-center w-full text-left px-2 py-1.5 rounded-md text-sm font-medium text-[var(--foreground)] hover:bg-[var(--background)]/70 transition-colors"
      :class="level === 0 ? 'bg-[var(--background)]/50' : ''"
      @click="toggle(sectionId)"
    >
      <UIcon :name="isExpanded ? 'i-fa6-solid-chevron-down' : 'i-fa6-solid-chevron-right'" class="mr-2 text-xs" />
      <span class="truncate">{{ section.title }}</span>
    </button>

    <div
      v-if="isExpanded"
      class="ml-4 mt-1 space-y-1"
      :class="level > 0 ? 'pl-2 border-l border-[var(--border-color)]/30' : ''"
    >
      <template v-for="pid in section.pages" :key="pid">
        <button
          v-if="pageFor(pid)"
          class="w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors"
          :class="currentPageId === pid
            ? 'bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] border border-[var(--accent-primary)]/30'
            : 'text-[var(--foreground)] hover:bg-[var(--background)] border border-transparent'"
          @click="select(pid)"
        >
          <div class="flex items-center">
            <div class="w-2 h-2 rounded-full mr-2 flex-shrink-0" :class="dotClass(pageFor(pid)!.importance)" />
            <span class="truncate">{{ pageFor(pid)!.title }}</span>
          </div>
        </button>
      </template>

      <WikiTreeSection
        v-for="sid in (section.subsections || [])"
        :key="sid"
        :section-id="sid"
        :level="level + 1"
        :wiki-structure="wikiStructure"
        :current-page-id="currentPageId"
        :expanded="expanded"
        :toggle="toggle"
        :select="select"
      />
    </div>
  </div>
</template>
