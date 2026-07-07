<script setup lang="ts">
// 结构化需求提交（FR-REQ-01）。支持 ?parent=<id> 创建子需求（类型锁定为系统需求、项目继承父需求）。
// 附件上传（FR-REQ-01 的一部分）待后端支持，一期 backlog。
import type { Project, Requirement } from '~/types/requirement'

definePageMeta({ layout: 'home' })

const route = useRoute()
const toast = useToast()

const parentId = computed(() => {
  const p = Number(route.query.parent)
  return Number.isInteger(p) && p > 0 ? p : null
})
const { data: parent } = useFetch<Requirement>(
  () => `/api/requirements/${parentId.value}`,
  { immediate: !!parentId.value, default: () => null as Requirement | null },
)

const { data: projects, refresh: refreshProjects } = useFetch<Project[]>('/api/projects', { default: () => [] })
const projectItems = computed(() => (projects.value || []).map(p => ({ label: `${p.name}（${p.code}）`, value: p.id })))

const form = reactive({
  project_id: null as number | null,
  req_type: 'business' as 'business' | 'system',
  title: '',
  description: '',
  priority: 'P1' as 'P0' | 'P1' | 'P2',
  expected_online_date: '',
})

// 子需求：继承父需求项目、锁定为系统需求
watch(parent, (p) => {
  if (p) {
    form.project_id = p.project_id
    form.req_type = 'system'
  }
}, { immediate: true })

// 平台刚初始化时项目空间为空：提供最小快速建项，避免流程卡死（正式项目管理在 FR-ADM-02 管理页）
const quickProject = reactive({ code: '', name: '', pending: false })
async function createProject() {
  if (!quickProject.code.trim() || !quickProject.name.trim() || quickProject.pending) return
  quickProject.pending = true
  try {
    const created = await $fetch<Project>('/api/projects', {
      method: 'POST',
      body: { code: quickProject.code.trim(), name: quickProject.name.trim() },
    })
    await refreshProjects()
    form.project_id = created.id
    toast.add({ title: `项目「${created.name}」已创建`, color: 'success' })
  } catch (e: any) {
    toast.add({ title: '创建项目失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    quickProject.pending = false
  }
}

const submitting = ref(false)
async function submit() {
  if (submitting.value) return
  if (!form.project_id) {
    toast.add({ title: '请选择所属项目', color: 'warning' })
    return
  }
  if (!form.title.trim()) {
    toast.add({ title: '请填写需求标题', color: 'warning' })
    return
  }
  submitting.value = true
  try {
    const created = await $fetch<Requirement>('/api/requirements', {
      method: 'POST',
      body: {
        project_id: form.project_id,
        req_type: form.req_type,
        title: form.title.trim(),
        description: form.description,
        priority: form.priority,
        parent_id: parentId.value,
        expected_online_date: form.expected_online_date || null,
      },
    })
    toast.add({ title: `需求 #${created.id} 已创建（草稿）`, description: '提交分析后进入流转', color: 'success' })
    await navigateTo(`/requirements/${created.id}`)
  } catch (e: any) {
    toast.add({ title: '创建失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="max-w-2xl mx-auto p-4 sm:p-6 space-y-4">
      <div class="flex items-center gap-2">
        <UButton variant="ghost" color="neutral" icon="i-lucide-arrow-left" size="sm" :to="parentId ? `/requirements/${parentId}` : '/requirements'" />
        <h1 class="text-lg font-bold text-highlighted">{{ parentId ? '新建子需求（系统需求）' : '新建需求' }}</h1>
      </div>

      <UAlert
        v-if="parent"
        color="info"
        variant="subtle"
        icon="i-lucide-corner-down-right"
        :title="`父需求：#${parent.id} ${parent.title}`"
        description="子需求将继承父需求的所属项目，类型为系统需求"
      />

      <UCard>
        <form class="space-y-4" @submit.prevent="submit">
          <UFormField label="所属项目" required>
            <USelectMenu
              v-model="form.project_id"
              :items="projectItems"
              value-key="value"
              placeholder="选择项目"
              :disabled="!!parent"
              class="w-full"
            />
            <template v-if="!projectItems.length" #help>
              <span class="text-warning">暂无项目空间，先创建一个：</span>
            </template>
          </UFormField>

          <div v-if="!projectItems.length" class="flex gap-2 items-end p-3 rounded-lg bg-elevated/50">
            <UFormField label="项目代号" class="flex-1">
              <UInput v-model="quickProject.code" placeholder="galaxy-billing" class="w-full" />
            </UFormField>
            <UFormField label="项目名称" class="flex-1">
              <UInput v-model="quickProject.name" placeholder="银河开单系统" class="w-full" />
            </UFormField>
            <UButton variant="soft" :loading="quickProject.pending" @click="createProject">创建</UButton>
          </div>

          <UFormField label="需求类型" required>
            <URadioGroup
              v-model="form.req_type"
              orientation="horizontal"
              :disabled="!!parent"
              :items="[
                { label: '业务需求', value: 'business' },
                { label: '系统需求', value: 'system' },
              ]"
            />
          </UFormField>

          <UFormField label="需求标题" required>
            <UInput v-model="form.title" placeholder="一句话说清要做什么" maxlength="255" class="w-full" />
          </UFormField>

          <UFormField label="需求描述" hint="背景 / 目标 / 涉及业务域 / 验收期望">
            <UTextarea
              v-model="form.description"
              :rows="8"
              placeholder="【背景】为什么要做&#10;【目标】做成什么样、怎么衡量&#10;【涉及业务域】哪些系统或流程&#10;【验收期望】业务方如何确认"
              class="w-full"
            />
          </UFormField>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField label="优先级">
              <USelect
                v-model="form.priority"
                :items="[
                  { label: 'P0 — 必须', value: 'P0' },
                  { label: 'P1 — 重要', value: 'P1' },
                  { label: 'P2 — 一般', value: 'P2' },
                ]"
                class="w-full"
              />
            </UFormField>
            <UFormField label="期望上线时间">
              <UInput v-model="form.expected_online_date" type="date" class="w-full" />
            </UFormField>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton variant="ghost" color="neutral" :to="parentId ? `/requirements/${parentId}` : '/requirements'">取消</UButton>
            <UButton type="submit" :loading="submitting" icon="i-lucide-check">创建需求</UButton>
          </div>
        </form>
      </UCard>
    </div>
  </div>
</template>
