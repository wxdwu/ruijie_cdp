<script setup>
defineProps({
  interactions: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">互动时间线</div>
    <div class="space-y-4">
      <div
        v-for="(item, idx) in interactions"
        :key="idx"
        class="flex gap-4 pb-4 border-b border-[var(--line)] last:border-0 last:pb-0"
      >
        <div class="flex-shrink-0">
          <div class="w-2 h-2 rounded-full bg-[var(--brand)] mt-2"></div>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs text-[var(--muted)]">{{ item.time }}</span>
            <span class="text-xs px-2 py-0.5 rounded bg-white/5 text-[var(--muted)]">{{ item.source }}</span>
          </div>
          <div class="text-sm text-[var(--text)] mb-1">{{ item.who }}</div>
          <div class="text-sm text-[var(--muted)]">{{ item.content }}</div>
        </div>
      </div>
      <div v-if="!interactions || interactions.length === 0" class="text-center py-8 text-[var(--muted)]">
        暂无互动记录
      </div>
    </div>
  </div>
</template>
