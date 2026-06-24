<script setup>
import { useRoute } from 'vue-router'
import { computed, ref } from 'vue'
import { useCustomerStore } from '../../stores/customer'
import ExportButton from '../customer/ExportButton.vue'

const route = useRoute()
const customerStore = useCustomerStore()
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

const showCustomerExport = computed(() => route.path === '/customers')
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
      <ExportButton v-if="showCustomerExport" :filters="customerStore.filters" />
    </div>
  </header>
</template>
