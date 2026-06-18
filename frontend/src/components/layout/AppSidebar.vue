<script setup>
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const navItems = [
  { to: '/customers', label: '客户管理', icon: '👥' },
  { to: '/campaign', label: '营销看板', icon: '📊' },
  { to: '/ai-chat', label: 'AI 对话', icon: '🤖' },
  { to: '/review', label: '审核队列', icon: '✅' },
]

const route = useRoute()
const isActive = (path) => computed(() => route.path.startsWith(path))
</script>

<template>
  <aside
    class="app-sidebar flex w-56 flex-col border-r border-[var(--line)] bg-[var(--panel)] backdrop-blur"
  >
    <div class="flex items-center gap-2 px-5 py-5">
      <span class="text-xl">🎯</span>
      <span class="text-base font-bold tracking-wide text-[var(--brand)]">CDP ABM 360</span>
    </div>

    <nav class="mt-2 flex flex-1 flex-col gap-1 px-3">
      <router-link
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors"
        :class="
          isActive(item.to).value
            ? 'bg-[var(--brand)]/15 text-[var(--brand)]'
            : 'text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
        "
      >
        <span>{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="border-t border-[var(--line)] px-5 py-4 text-xs text-[var(--muted)]">
      v0.1.0
    </div>
  </aside>
</template>
