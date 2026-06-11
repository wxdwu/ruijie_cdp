<script setup>
defineProps({
  businessConclusion: { type: String, default: '-' },
  topContacts: { type: Array, default: () => [] },
  evidenceChain: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-lg">🧠</span>
      <span class="text-sm font-medium text-[var(--text)]">AI 洞察</span>
    </div>
    <div class="space-y-4">
      <!-- 业务结论 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">业务结论</div>
        <div class="text-sm text-[var(--text)] bg-white/5 rounded-lg p-3">
          {{ businessConclusion }}
        </div>
      </div>

      <!-- 推荐联系人 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">推荐联系人</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(contact, idx) in topContacts"
            :key="idx"
            class="inline-flex items-center gap-1 rounded-full bg-[var(--brand)]/10 text-[var(--brand)] border border-[var(--brand)]/20 px-3 py-1 text-sm"
          >
            <span>{{ contact.name }}</span>
            <span class="text-xs opacity-70">({{ contact.role }})</span>
          </span>
          <span v-if="!topContacts || topContacts.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>

      <!-- 证据链 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">证据链</div>
        <div class="space-y-2">
          <div
            v-for="(evidence, idx) in evidenceChain"
            :key="idx"
            class="flex items-start gap-2 text-sm"
          >
            <span class="text-[var(--brand)]">•</span>
            <span class="text-[var(--muted)]">{{ evidence }}</span>
          </div>
          <span v-if="!evidenceChain || evidenceChain.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>
    </div>
  </div>
</template>
