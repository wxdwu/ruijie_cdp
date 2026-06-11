<script setup>
defineProps({
  contact: {
    type: Object,
    default: () => ({
      name: '-',
      role: '-',
      department: '-',
      reason: '-',
    }),
  },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--brand)]/30 bg-[var(--brand)]/5 p-5">
    <div class="flex items-center gap-2 mb-3">
      <span class="text-lg">🤖</span>
      <span class="text-sm font-medium text-[var(--brand)]">AI 推荐优先联系人</span>
    </div>
    <div class="flex items-center justify-between">
      <div>
        <div class="text-lg font-medium text-[var(--text)]">{{ contact.name }}</div>
        <div class="text-sm text-[var(--muted)]">{{ contact.role }} · {{ contact.department }}</div>
      </div>
      <div class="max-w-md text-sm text-[var(--muted)] bg-white/5 rounded-lg p-3">
        {{ contact.reason }}
      </div>
    </div>
  </div>
</template>
