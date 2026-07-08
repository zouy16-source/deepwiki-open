<script setup lang="ts">
// 评审卡片（FR-REV-01/02）：发起评审（自动生成议程、圈选参会人）→ 录入结论驱动流转。
// start_review / approve / reject 三个状态机动作由本组件收敛，不走详情页通用按钮。
import type { Requirement, Review } from '~/types/requirement'

const props = defineProps<{ requirement: Requirement }>()
const emit = defineEmits<{ changed: [] }>()

const toast = useToast()

const { data: reviews, refresh: refreshReviews } = useFetch<Review[]>(
  () => `/api/requirements/${props.requirement.id}/reviews`,
  { default: () => [], watch: [() => props.requirement.id] },
)

const openReview = computed(() => reviews.value?.find(r => r.conclusion === null) || null)
const canStart = computed(() => props.requirement.status === 'analyzed' && !openReview.value)
const canConclude = computed(() => !!openReview.value && props.requirement.status === 'in_review')

// ---- 发起评审 ----
const createOpen = ref(false)
const creating = ref(false)
const createForm = reactive({
  participants: [] as string[],
  scheduled_at: '',
  agenda: '',
})

const { users, displayName } = usePlatformUsers()
const userItems = computed(() =>
  (users.value || [])
    .filter(u => u.is_active)
    .map(u => ({ label: u.display_name ? `${u.display_name}（${u.username}）` : u.username, value: u.username })),
)

async function createReview() {
  if (creating.value) return
  creating.value = true
  try {
    await $fetch(`/api/requirements/${props.requirement.id}/reviews`, {
      method: 'POST',
      body: {
        participants: createForm.participants,
        scheduled_at: createForm.scheduled_at || null,
        agenda: createForm.agenda.trim() || null,
      },
    })
    toast.add({ title: '评审已发起', description: '需求进入「评审中」，议程已生成', color: 'success' })
    createOpen.value = false
    Object.assign(createForm, { participants: [], scheduled_at: '', agenda: '' })
    await refreshReviews()
    emit('changed')
  } catch (e: any) {
    toast.add({ title: '发起评审失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    creating.value = false
  }
}

// ---- 录入结论 ----
const concludeTarget = ref<'approved' | 'conditional' | 'rejected' | null>(null)
const concludeComment = ref('')
const concluding = ref(false)

function openConclude(c: 'approved' | 'conditional' | 'rejected') {
  concludeTarget.value = c
  concludeComment.value = ''
}

async function concludeReview() {
  const c = concludeTarget.value
  if (!c || !openReview.value || concluding.value) return
  concluding.value = true
  try {
    await $fetch(`/api/reviews/${openReview.value.id}/conclude`, {
      method: 'POST',
      body: { conclusion: c, comment: concludeComment.value },
    })
    toast.add({
      title: `评审结论：${REVIEW_CONCLUSIONS[c]?.label}`,
      description: c === 'rejected' ? '需求已打回' : '需求进入「已排期」',
      color: c === 'rejected' ? 'warning' : 'success',
    })
    concludeTarget.value = null
    await refreshReviews()
    emit('changed')
  } catch (e: any) {
    toast.add({ title: '录入结论失败', description: e?.data?.detail || e?.statusMessage || '请重试', color: 'error' })
  } finally {
    concluding.value = false
  }
}

const expandedAgenda = ref<number | null>(null)
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium text-highlighted">评审 {{ reviews?.length ? `· ${reviews.length}` : '' }}</span>
        <UButton
          v-if="canStart"
          size="xs"
          icon="i-lucide-gavel"
          @click="createOpen = true"
        >
          发起评审
        </UButton>
      </div>
    </template>

    <div v-if="reviews?.length" class="space-y-4">
      <div
        v-for="rv in reviews"
        :key="rv.id"
        class="border border-default rounded-lg p-3 space-y-2"
        :class="rv.conclusion === null ? 'border-primary/40' : ''"
      >
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-xs text-muted">#{{ rv.id }}</span>
          <UBadge
            v-if="rv.conclusion"
            :label="REVIEW_CONCLUSIONS[rv.conclusion]?.label || rv.conclusion"
            :color="(REVIEW_CONCLUSIONS[rv.conclusion]?.color as any) || 'neutral'"
            variant="subtle"
            size="sm"
          />
          <UBadge v-else label="评审中" color="primary" variant="subtle" size="sm" />
          <span class="text-xs text-muted">
            <span :title="rv.initiator">{{ displayName(rv.initiator) }}</span> 发起于 {{ fmtTime(rv.created_at) }}
            <template v-if="rv.scheduled_at"> · 会议时间 {{ fmtTime(rv.scheduled_at) }}</template>
          </span>
          <UButton
            variant="link"
            color="neutral"
            size="xs"
            class="ml-auto"
            :trailing-icon="expandedAgenda === rv.id ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
            @click="expandedAgenda = expandedAgenda === rv.id ? null : rv.id"
          >
            议程
          </UButton>
        </div>

        <div v-if="rv.participants.length" class="flex flex-wrap items-center gap-1.5">
          <UIcon name="i-lucide-users" class="size-3.5 text-dimmed" />
          <UBadge v-for="p in rv.participants" :key="p" :label="displayName(p)" :title="p" color="neutral" variant="outline" size="sm" />
        </div>

        <pre
          v-if="expandedAgenda === rv.id"
          class="text-xs text-muted whitespace-pre-wrap bg-elevated/50 rounded p-3 max-h-80 overflow-y-auto"
        >{{ rv.agenda }}</pre>

        <p v-if="rv.conclusion" class="text-sm text-muted">
          <span class="font-medium text-highlighted" :title="rv.concluded_by || ''">{{ displayName(rv.concluded_by) }}</span>
          于 {{ fmtTime(rv.concluded_at) }} 录入结论
          <template v-if="rv.conclusion_comment">：{{ rv.conclusion_comment }}</template>
        </p>

        <div v-else-if="canConclude" class="flex flex-wrap gap-2 pt-1">
          <UButton size="xs" color="success" @click="openConclude('approved')">通过</UButton>
          <UButton size="xs" color="warning" variant="soft" @click="openConclude('conditional')">有条件通过</UButton>
          <UButton size="xs" color="error" variant="soft" @click="openConclude('rejected')">打回</UButton>
        </div>
      </div>
    </div>

    <p v-else class="text-sm text-muted">
      暂无评审记录。
      <template v-if="requirement.status === 'analyzed'">需求已分析完成，可发起评审。</template>
      <template v-else>需求进入「分析完成」后可发起评审。</template>
    </p>

    <!-- 发起评审弹窗 -->
    <UModal
      v-model:open="createOpen"
      title="发起评审"
      description="将驱动需求进入「评审中」；议程自动生成（含需求摘要与待决议项）"
    >
      <template #body>
        <div class="space-y-4">
          <UFormField label="参会人" hint="从平台用户中圈选">
            <USelectMenu
              v-model="createForm.participants"
              :items="userItems"
              value-key="value"
              multiple
              placeholder="选择参会人（可多选）"
              class="w-full"
            />
          </UFormField>
          <UFormField label="会议时间（可选）">
            <UInput v-model="createForm.scheduled_at" type="datetime-local" class="w-full" />
          </UFormField>
          <UFormField label="自定义议程（可选）" hint="留空则按模板自动生成：需求摘要 + AI 分析结论占位 + 待决议项">
            <UTextarea v-model="createForm.agenda" :rows="5" placeholder="留空自动生成" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton variant="ghost" color="neutral" @click="createOpen = false">取消</UButton>
          <UButton icon="i-lucide-gavel" :loading="creating" @click="createReview">发起评审</UButton>
        </div>
      </template>
    </UModal>

    <!-- 结论确认弹窗 -->
    <UModal
      :open="!!concludeTarget"
      :title="`评审结论：${concludeTarget ? REVIEW_CONCLUSIONS[concludeTarget]?.label : ''}`"
      :description="concludeTarget === 'rejected' ? '需求将打回（可补充后重新提交）' : '需求将进入「已排期」'"
      @update:open="(v: boolean) => { if (!v) concludeTarget = null }"
    >
      <template #body>
        <UFormField :label="concludeTarget === 'approved' ? '评审意见（可选）' : '评审意见（建议填写原因/条件）'">
          <UTextarea v-model="concludeComment" :rows="4" placeholder="评审结论依据、附加条件、打回原因…" class="w-full" autofocus />
        </UFormField>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton variant="ghost" color="neutral" @click="concludeTarget = null">取消</UButton>
          <UButton
            :color="(concludeTarget ? REVIEW_CONCLUSIONS[concludeTarget]?.color as any : 'primary')"
            :loading="concluding"
            @click="concludeReview"
          >
            确认录入
          </UButton>
        </div>
      </template>
    </UModal>
  </UCard>
</template>
