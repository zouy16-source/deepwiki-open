<script setup lang="ts">
// 平台登录页（FR-ADM-01）：企业 LDAP/AD 账号登录，无本地注册。
definePageMeta({ layout: false })

const route = useRoute()
const { state, login } = useAuthSession()

const username = ref('')
const password = ref('')
const pending = ref(false)
const errorMsg = ref('')

// 已登录（或本地免鉴权模式）直接回首页
onMounted(() => {
  if (state.value && (!state.value.enabled || state.value.user)) {
    navigateTo(redirectTarget(), { replace: true })
  }
})

function redirectTarget(): string {
  const r = route.query.redirect
  return typeof r === 'string' && r.startsWith('/') ? r : '/'
}

async function submit() {
  if (pending.value) return
  if (!username.value.trim() || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  pending.value = true
  errorMsg.value = ''
  try {
    await login(username.value.trim(), password.value)
    await navigateTo(redirectTarget(), { replace: true })
  } catch (e) {
    const status = (e as { statusCode?: number, response?: { status?: number } })?.statusCode
      ?? (e as { response?: { status?: number } })?.response?.status
    errorMsg.value
      = status === 401
        ? '用户名或密码错误'
        : status === 429
          ? '尝试过于频繁，请稍后再试'
          : '认证服务不可用，请联系平台管理员'
    password.value = ''
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-default p-4">
    <UCard class="w-full max-w-sm">
      <template #header>
        <div class="flex items-center gap-3">
          <span class="inline-flex items-center justify-center size-10 rounded-lg bg-primary text-inverted">
            <UIcon name="i-lucide-book-open-text" class="size-6" />
          </span>
          <div>
            <p class="font-bold text-highlighted">DevFlow AI</p>
            <p class="text-xs text-muted">使用企业账号（LDAP/AD）登录</p>
          </div>
        </div>
      </template>

      <form class="space-y-4" @submit.prevent="submit">
        <UFormField label="用户名">
          <UInput
            v-model="username"
            autocomplete="username"
            placeholder="域账号，如 zhangsan"
            icon="i-lucide-user"
            class="w-full"
            autofocus
          />
        </UFormField>

        <UFormField label="密码">
          <UInput
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="域账号密码"
            icon="i-lucide-lock"
            class="w-full"
          />
        </UFormField>

        <UAlert
          v-if="errorMsg"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="errorMsg"
        />

        <UButton type="submit" block :loading="pending">
          登录
        </UButton>
      </form>

      <template #footer>
        <p class="text-xs text-muted text-center">
          账号由企业目录统一管理，如无法登录请联系平台管理员
        </p>
      </template>
    </UCard>
  </div>
</template>
