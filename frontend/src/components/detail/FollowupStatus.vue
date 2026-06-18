<script setup>
const props = defineProps({
  lastInteraction: { type: [String, Date, Object], default: '-' },
  preferredChannels: { type: [String, Array], default: () => [] },
  cumulativeCount: { type: [Number, String], default: 0 },
  effectiveCount: { type: [Number, String], default: 0 },
})

const channelMap = {
  email: '邮件',
  web: '官网',
  event: '直播/活动',
  wechat: '微信',
  phone: '电话',
  offline: '线下',
}

function formatChannels() {
  let channels = props.preferredChannels
  // Handle JSON string
  if (typeof channels === 'string') {
    try { channels = JSON.parse(channels) } catch (e) { return [channels] }
  }
  if (!Array.isArray(channels)) return []
  return channels.map(c => channelMap[c] || c)
}

function formatTime(val) {
  if (!val || val === '-') return '-'
  try {
    const d = new Date(val)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch (e) { return val }
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">跟进状态</div>
    <div class="divide-y divide-[var(--line)]">
      <div class="grid min-h-12 grid-cols-[110px_1fr] items-center gap-4 py-3 first:pt-0">
        <div class="text-xs text-[var(--muted)]">最近互动</div>
        <div class="text-right text-sm text-[var(--text)]">{{ formatTime(lastInteraction) }}</div>
      </div>
      <div class="grid min-h-12 grid-cols-[110px_1fr] items-center gap-4 py-3">
        <div class="text-xs text-[var(--muted)]">累计/计划/有效</div>
        <div class="text-right text-sm font-semibold text-[var(--text)]">
          {{ cumulativeCount ?? 0 }} / 0 / {{ effectiveCount ?? 0 }}
        </div>
      </div>
      <div class="grid min-h-12 grid-cols-[110px_1fr] items-center gap-4 py-3 last:pb-0">
        <div class="text-xs text-[var(--muted)]">偏好渠道</div>
        <div class="flex flex-wrap justify-end gap-2">
          <span
            v-for="(channel, idx) in formatChannels()"
            :key="idx"
            class="inline-flex items-center rounded-full bg-[var(--brand)]/10 text-[var(--brand)] border border-[var(--brand)]/20 px-2.5 py-0.5 text-xs"
          >
            {{ channel }}
          </span>
          <span v-if="formatChannels().length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>
    </div>
  </div>
</template>
