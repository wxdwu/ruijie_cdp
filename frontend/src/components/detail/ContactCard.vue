<script setup>
const props = defineProps({
  contact: { type: Object, default: () => ({}) },
})

const roleColors = {
  '决策者': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  '拍板者': 'bg-red-500/20 text-red-400 border-red-500/30',
  '技术评估者': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '使用者': 'bg-green-500/20 text-green-400 border-green-500/30',
  '其他': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const activityColors = {
  '高': 'bg-green-500/20 text-green-400',
  'medium': 'bg-green-500/20 text-green-400',
  '中': 'bg-yellow-500/20 text-yellow-400',
  '低': 'bg-gray-500/20 text-gray-400',
  'none': 'bg-gray-500/20 text-gray-400',
}

function formatTime(val) {
  if (!val) return '-'
  try {
    const d = new Date(val)
    return d.toLocaleDateString('zh-CN')
  } catch (e) { return val }
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 hover:border-[var(--brand)]/50 transition-colors">
    <div class="flex items-start justify-between mb-4">
      <div>
        <div class="text-lg font-medium text-[var(--text)]">{{ contact.contact_name || '未命名' }}</div>
        <div class="text-sm text-[var(--muted)]">{{ contact.department || '-' }}</div>
      </div>
      <div class="flex gap-2">
        <span
          v-if="contact.role_category"
          class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
          :class="roleColors[contact.role_category] || roleColors['其他']"
        >
          {{ contact.role_category }}
        </span>
        <span
          v-if="contact.activity_level"
          class="inline-flex items-center rounded-full px-2 py-0.5 text-xs"
          :class="activityColors[contact.activity_level] || activityColors['低']"
        >
          {{ contact.activity_level }}
        </span>
      </div>
    </div>
    <div class="space-y-2 mb-4">
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">📱</span>
        <span class="text-[var(--text)]">{{ contact.mobile || '-' }}</span>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">📧</span>
        <span class="text-[var(--text)]">{{ contact.email || '-' }}</span>
      </div>
    </div>
    <div class="flex items-center justify-between pt-3 border-t border-[var(--line)] text-xs">
      <span class="text-[var(--muted)]">互动 {{ contact.interaction_count || 0 }} 次</span>
      <span class="text-[var(--muted)]">最近: {{ formatTime(contact.last_interaction_time) }}</span>
    </div>
  </div>
</template>