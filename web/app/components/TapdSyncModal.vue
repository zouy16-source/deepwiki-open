<script setup lang="ts">
// 从 TAPD 同步需求（单向只读镜像）。自助流程：选项目 → 缺 workspace/nick 时内联绑定 → 同步。
import type { PlatformUser, Project } from '~/types/requirement'

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ synced: [] }>()

const toast = useToast()

const { data: projects, refresh: refreshProjects } = useFetch<Project[]>('/api/projects', { default: () => [] })
const { data: me, refresh: refreshMe } = useFetch<PlatformUser & { registered?: boolean }>('/api/users/me', { default: () => null })

const projectId = ref<number | null>(null)
watch(projects, (ps) => { if (ps?.length && projectId.value === null) projectId.value = ps[0]!.id }, { immediate: true })
const project = computed(() => projects.value?.find(p => p.id === projectId.value) || null)
const projectItems = computed(() => (projects.value || []).map(p => ({ label: p.name, value: p.id })))

// 缺失项内联绑定
const workspaceInput = ref('')
const nickInput = ref('')
watch(project, (p) => { workspaceInput.value = p?.tapd_workspace_id || '' }, { immediate: true })
watch(me, (u) => { nickInput.value = u?.tapd_nick || '' }, { immediate: true })

const needWorkspace = computed(() => !!project.value && !project.value.tapd_workspace_id)
const needNick = computed(() => !!me.value && !me.value.tapd_nick)

const binding = ref(false)
async function bindWorkspace() {
  if (!projectId.value || !workspaceInput.value.trim() || binding.value) return
  binding.value = true
  try {
    await $fetch(`/api/projects/${projectId.value}`, { method: 'PATCH', body: { tapd_workspace_id: workspaceInput.value.trim() } })
    await refreshProjects()
    toast.add({ title: 'TAPD workspace 已绑定', color: 'success' })
  } catch (e: any) {
    toast.add({ title: '绑定失败', description: e?.data?.detail || e?.statusMessage, color: 'error' })
  } finally { binding.value = false }
}
async function bindNick() {
  if (!nickInput.value.trim() || binding.value) return
  binding.value = true
  try {
    await $fetch('/api/users/me', { method: 'PATCH', body: { tapd_nick: nickInput.value.trim() } })
    await refreshMe()
    toast.add({ title: 'TAPD 账号已绑定', color: 'success' })
  } catch (e: any) {
    toast.add({ title: '绑定失败', description: e?.data?.detail || e?.statusMessage, color: 'error' })
  } finally { binding.value = false }
}

const syncing = ref(false)
async function sync() {
  if (!projectId.value || syncing.value) return
  syncing.value = true
  try {
    const res = await $fetch<{ created: number, updated: number, total: number }>('/api/tapd/sync', {
      method: 'POST',
      body: { project_id: projectId.value },
    })
    toast.add({
      title: 'TAPD 同步完成',
      description: `共 ${res.total} 条：新增 ${res.created}、更新 ${res.updated}`,
      color: 'success',
    })
    open.value = false
    emit('synced')
  } catch (e: any) {
    toast.add({ title: '同步失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally { syncing.value = false }
}
</script>

<template>
  <UModal v-model:open="open" title="从 TAPD 同步需求" description="单向只读镜像：拉取你在 TAPD 名下的需求，可在平台做 AI 分析">
    <template #body>
      <div class="space-y-4">
        <UFormField label="同步到项目" required>
          <USelect v-model="projectId" :items="projectItems" class="w-full" />
        </UFormField>

        <UFormField v-if="needWorkspace" label="TAPD workspace id" hint="该项目尚未绑定 TAPD 项目，请填写 workspace_id 后绑定">
          <div class="flex gap-2">
            <UInput v-model="workspaceInput" placeholder="如 10104801" class="flex-1" />
            <UButton variant="soft" :loading="binding" :disabled="!workspaceInput.trim()" @click="bindWorkspace">绑定</UButton>
          </div>
        </UFormField>

        <UFormField v-if="needNick" label="你的 TAPD 账号（nick）" hint="按当前用户同步需先绑定 TAPD 账号（用于 owner 过滤）">
          <div class="flex gap-2">
            <UInput v-model="nickInput" placeholder="TAPD 显示名 / nick" class="flex-1" />
            <UButton variant="soft" :loading="binding" :disabled="!nickInput.trim()" @click="bindNick">绑定</UButton>
          </div>
        </UFormField>

        <UAlert
          v-if="!needWorkspace && !needNick"
          color="info"
          variant="subtle"
          icon="i-lucide-info"
          title="将拉取你在该 TAPD 项目中作为处理人的需求"
          description="重复同步按需求幂等更新，不会重复；平台侧的 AI 分析/评审不受覆盖影响"
        />
      </div>
    </template>
    <template #footer>
      <div class="flex justify-end gap-2 w-full">
        <UButton variant="ghost" color="neutral" @click="open = false">取消</UButton>
        <UButton
          icon="i-lucide-refresh-cw"
          :loading="syncing"
          :disabled="!projectId || needWorkspace || needNick"
          @click="sync"
        >
          开始同步
        </UButton>
      </div>
    </template>
  </UModal>
</template>
