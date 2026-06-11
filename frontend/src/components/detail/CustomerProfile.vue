<script setup>
defineProps({
  industry: { type: String, default: '-' },
  region: { type: String, default: '-' },
  owner: { type: String, default: '-' },
  telecomAddress: { type: String, default: '-' },
  isExistingCustomer: { type: Boolean, default: false },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">客户档案</div>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <div class="text-xs text-[var(--muted)] mb-1">行业</div>
        <div class="text-sm text-[var(--text)]">{{ industry }}</div>
      </div>
      <div>
        <div class="text-xs text-[var(--muted)] mb-1">区域</div>
        <div class="text-sm text-[var(--text)]">{{ region }}</div>
      </div>
      <div>
        <div class="text-xs text-[var(--muted)] mb-1">客户经理</div>
        <div class="text-sm text-[var(--text)]">{{ owner }}</div>
      </div>
      <div>
        <div class="text-xs text-[var(--muted)] mb-1">电信地址</div>
        <div class="text-sm text-[var(--text)]">{{ telecomAddress }}</div>
      </div>
    </div>
    <div class="mt-4 pt-4 border-t border-[var(--line)]">
      <div class="flex items-center gap-2">
        <span
          class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
          :class="isExistingCustomer ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'"
        >
          {{ isExistingCustomer ? '存量客户' : '新客户' }}
        </span>
      </div>
    </div>
  </div>
</template>
