<script setup lang="ts">
// Rich-text markdown editor built on Nuxt UI's <UEditor> (Tiptap) with a toolbar.
// `.client` so it never SSRs. v-model is the markdown source (content-type="markdown"),
// so it round-trips as markdown and stays compatible with the rest of the pipeline.
const model = defineModel<string>({ default: '' })

// Toolbar groups: undo/redo · headings · marks · lists & blocks · link/rule.
// Each item = UButton props (icon/aria-label) + an editor `kind` that UEditor maps
// to the matching Tiptap command (and reflects active state).
const items = [
  [
    { icon: 'i-lucide-undo-2', kind: 'undo', 'aria-label': '撤销' },
    { icon: 'i-lucide-redo-2', kind: 'redo', 'aria-label': '重做' },
  ],
  [
    { icon: 'i-lucide-heading-1', kind: 'heading', level: 1, 'aria-label': '一级标题' },
    { icon: 'i-lucide-heading-2', kind: 'heading', level: 2, 'aria-label': '二级标题' },
    { icon: 'i-lucide-heading-3', kind: 'heading', level: 3, 'aria-label': '三级标题' },
  ],
  [
    { icon: 'i-lucide-bold', kind: 'mark', mark: 'bold', 'aria-label': '加粗' },
    { icon: 'i-lucide-italic', kind: 'mark', mark: 'italic', 'aria-label': '斜体' },
    { icon: 'i-lucide-strikethrough', kind: 'mark', mark: 'strike', 'aria-label': '删除线' },
    { icon: 'i-lucide-code', kind: 'mark', mark: 'code', 'aria-label': '行内代码' },
  ],
  [
    { icon: 'i-lucide-list', kind: 'bulletList', 'aria-label': '无序列表' },
    { icon: 'i-lucide-list-ordered', kind: 'orderedList', 'aria-label': '有序列表' },
    { icon: 'i-lucide-list-checks', kind: 'taskList', 'aria-label': '任务列表' },
    { icon: 'i-lucide-quote', kind: 'blockquote', 'aria-label': '引用' },
    { icon: 'i-lucide-square-code', kind: 'codeBlock', 'aria-label': '代码块' },
  ],
  [
    { icon: 'i-lucide-link', kind: 'link', 'aria-label': '链接' },
    { icon: 'i-lucide-minus', kind: 'horizontalRule', 'aria-label': '分隔线' },
  ],
] as any
</script>

<template>
  <UEditor
    v-model="model"
    content-type="markdown"
    :ui="{ root: 'border border-default rounded-lg overflow-hidden flex flex-col h-full', content: 'prose prose-sm dark:prose-invert max-w-none p-4 overflow-y-auto flex-1 focus:outline-none' }"
  >
    <template #default="{ editor }">
      <UEditorToolbar
        :editor="editor"
        :items="items"
        class="border-b border-default bg-muted/40 flex-wrap gap-0.5 p-1"
      />
    </template>
  </UEditor>
</template>
