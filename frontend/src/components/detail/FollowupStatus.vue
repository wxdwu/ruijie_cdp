<script setup>
defineProps({
  lastInteraction: { type: String, default: '-' },
  preferredChannels: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">跟进状态</div>
    <div class="space-y-4">
      <div>
        <div class="text-xs text-[var(--muted)] mb-1">最近互动</div>
        <div class="text-sm text-[var(--text)]">{{ lastInteraction }}</div>
      </div>
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">偏好渠道</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(channel, idx) in preferredChannels"
            :key="idx"
            class="inline-flex items-center rounded-full bg-[var(--brand)]/10 text-[var(--brand)] border border-[var(--brand)]/20 px-2.5 py-0.5 text-xs"
          >
            {{ channel }}
          </span>
          <span v-if="!preferredChannels || preferredChannels.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>
    </div>
  </div>
</template>
