<script setup>
import { useRoute } from 'vue-router'
import { computed, ref } from 'vue'

const route = useRoute()
const theme = ref(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')

function applyTheme(value) {
  theme.value = value
  document.documentElement.dataset.theme = value
  localStorage.setItem('cdp-theme', value)
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

const titleMap = {
  '/customers': '客户管理',
  '/campaign': '营销活动看板',
  '/ai-chat': 'AI 智能对话',
  '/review': '审核队列',
}

const pageTitle = computed(() => {
  for (const [path, title] of Object.entries(titleMap)) {
    if (route.path.startsWith(path)) return title
  }
  return 'CDP ABM 360'
})
</script>

<template>
  <header
    class="flex items-center justify-between border-b border-[var(--line)] bg-[var(--panel)] px-6 py-3 backdrop-blur"
  >
    <h2 class="text-lg font-semibold">{{ pageTitle }}</h2>
    <div class="flex items-center gap-3">
      <button
        type="button"
        class="theme-toggle rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-[var(--surface-hover)]"
        :aria-label="theme === 'dark' ? '切换浅色主题' : '切换深色主题'"
        @click="toggleTheme"
      >
        {{ theme === 'dark' ? '切换浅色主题' : '切换深色主题' }}
      </button>
      <button
        class="rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
      >
        🔔 通知
      </button>
      <button
        class="rounded-lg bg-[var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition-colors hover:brightness-110"
      >
        + 新建
      </button>
    </div>
  </header>
</template>
