<script setup>
const props = defineProps({
  funnelCount: { type: Number, default: 0 },
  highestStage: { type: String, default: '-' },
  recentDeals: { type: [Number, String], default: 0 },
  historicalDeals: { type: [Number, String], default: null },
  productBudget: { type: [Number, String], default: 0 },
})

function formatAmount(val) {
  if (val === null || val === undefined || val === '') return '-'
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
    <div class="grid grid-cols-2 overflow-hidden rounded-lg border border-[var(--line)]">
      <div class="min-h-24 border-b border-r border-[var(--line)] p-4">
        <div class="mb-2 text-xs text-[var(--muted)]">漏斗商机数</div>
        <div class="text-xl font-bold text-[var(--text)]">{{ funnelCount }}</div>
      </div>
      <div class="min-h-24 border-b border-[var(--line)] p-4">
        <div class="mb-2 text-xs text-[var(--muted)]">最高阶段</div>
        <div class="text-sm font-semibold text-[var(--text)]">{{ highestStage }}</div>
      </div>
      <div class="min-h-24 border-r border-[var(--line)] p-4">
        <div class="mb-2 text-xs text-[var(--muted)]">近两年成交 / 历史</div>
        <div class="text-sm font-bold text-[var(--brand)]">
          {{ formatAmount(recentDeals) }} / {{ formatAmount(historicalDeals) }}
        </div>
      </div>
      <div class="min-h-24 p-4">
        <div class="mb-2 text-xs text-[var(--muted)]">产品预算</div>
        <div class="text-lg font-bold text-[var(--text)]">{{ formatAmount(productBudget) }}</div>
      </div>
    </div>
  </div>
</template>
