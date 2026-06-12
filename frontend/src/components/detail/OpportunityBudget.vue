<script setup>
const props = defineProps({
  funnelCount: { type: Number, default: 0 },
  highestStage: { type: String, default: '-' },
  recentDeals: { type: [Number, String], default: 0 },
})

function formatAmount(val) {
  if (val === null || val === undefined || val === 0) return '-'
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return '-'
  // Convert to 万元 (assuming the raw value is in yuan)
  if (num >= 10000) {
    return `${(num / 10000).toFixed(1).replace(/\.0$/, '')}万元`
  }
  return `${num}元`
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">商机预算</div>
    <div class="space-y-4">
      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="text-xs text-[var(--muted)] mb-1">漏斗商机数</div>
          <div class="text-xl font-bold text-[var(--text)]">{{ funnelCount }}</div>
        </div>
        <div>
          <div class="text-xs text-[var(--muted)] mb-1">最高阶段</div>
          <div class="text-sm font-medium text-[var(--text)]">{{ highestStage }}</div>
        </div>
      </div>
      <div class="pt-4 border-t border-[var(--line)]">
        <div class="text-xs text-[var(--muted)] mb-2">成交金额</div>
        <div class="text-lg font-bold text-[var(--brand)]">{{ formatAmount(recentDeals) }}</div>
      </div>
    </div>
  </div>
</template>
