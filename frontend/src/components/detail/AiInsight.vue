<script setup>
defineProps({
  businessConclusion: { type: Array, default: () => [] },
  topContacts: { type: Array, default: () => [] },
  evidenceChain: { type: Object, default: () => ({}) },
})

function evidenceLabel(key) {
  const map = {
    intent_score: '意向分',
    intent_level: '意向等级',
    interaction_count: '互动次数',
    opportunity_count: '商机数',
    contact_count: '联系人',
    mobile_count: '手机号',
    last_interaction_time: '最近互动',
    last_interaction_channel: '最近渠道',
  }
  return map[key] || key
}
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
        <div class="space-y-2">
          <div
            v-for="(line, idx) in businessConclusion"
            :key="idx"
            class="text-sm text-[var(--text)] bg-white/5 rounded-lg p-3"
          >
            {{ line }}
          </div>
          <div v-if="!businessConclusion || businessConclusion.length === 0" class="text-xs text-[var(--muted)] bg-white/5 rounded-lg p-3">
            暂无业务结论
          </div>
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
            {{ contact }}
          </span>
          <span v-if="!topContacts || topContacts.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>

      <!-- 证据链 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">证据链</div>
        <div class="grid grid-cols-2 gap-2">
          <div
            v-for="(val, key) in evidenceChain"
            :key="key"
            class="flex items-center gap-2 text-sm bg-white/5 rounded-lg px-3 py-2"
          >
            <span class="text-[var(--muted)] text-xs">{{ evidenceLabel(key) }}:</span>
            <span class="text-[var(--text)] font-medium">{{ val }}</span>
          </div>
        </div>
        <div v-if="Object.keys(evidenceChain).length === 0" class="text-xs text-[var(--muted)] mt-2">
          暂无证据
        </div>
      </div>
    </div>
  </div>
</template>