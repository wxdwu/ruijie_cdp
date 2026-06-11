<script setup>
defineProps({
  funnelCount: { type: Number, default: 0 },
  highestStage: { type: String, default: '-' },
  recentDeals: { type: Array, default: () => [] },
})
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
        <div class="text-xs text-[var(--muted)] mb-2">最近成交</div>
        <div class="space-y-2">
          <div
            v-for="(deal, idx) in recentDeals"
            :key="idx"
            class="flex items-center justify-between text-sm"
          >
            <span class="text-[var(--text)]">{{ deal.name }}</span>
            <span class="text-[var(--muted)]">{{ deal.date }}</span>
          </div>
          <span v-if="!recentDeals || recentDeals.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>
    </div>
  </div>
</template>
