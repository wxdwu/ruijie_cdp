<script setup>
defineProps({
  contact: {
    type: Object,
    default: () => ({
      name: '-',
      role: '-',
      department: '-',
      phone: '-',
      email: '-',
      importance: '中',
    }),
  },
})

const roleColors = {
  '拍板者': 'bg-red-500/20 text-red-400 border-red-500/30',
  '决策者': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  '技术评估者': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '使用者': 'bg-green-500/20 text-green-400 border-green-500/30',
  '其他': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const importanceColors = {
  '高': 'bg-red-500/20 text-red-400',
  '中': 'bg-yellow-500/20 text-yellow-400',
  '低': 'bg-gray-500/20 text-gray-400',
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 hover:border-[var(--brand)]/50 transition-colors">
    <div class="flex items-start justify-between mb-4">
      <div>
        <div class="text-lg font-medium text-[var(--text)]">{{ contact.name }}</div>
        <div class="text-sm text-[var(--muted)]">{{ contact.department }}</div>
      </div>
      <div class="flex gap-2">
        <span
          class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
          :class="roleColors[contact.role] || roleColors['其他']"
        >
          {{ contact.role }}
        </span>
        <span
          class="inline-flex items-center rounded-full px-2 py-0.5 text-xs"
          :class="importanceColors[contact.importance] || importanceColors['中']"
        >
          {{ contact.importance }}
        </span>
      </div>
    </div>
    <div class="space-y-2">
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">📱</span>
        <span class="text-[var(--text)]">{{ contact.phone }}</span>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">📧</span>
        <span class="text-[var(--text)]">{{ contact.email }}</span>
      </div>
    </div>
  </div>
</template>
