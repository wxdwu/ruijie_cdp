<script setup>
defineProps({
  demandTypes: { type: Array, default: () => [] },
  businessScenarios: { type: Array, default: () => [] },
  painPoints: { type: Array, default: () => [] },
  productCategories: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5">
    <div class="text-sm font-medium text-[var(--text)] mb-4">业务标签</div>
    <div class="space-y-4">
      <!-- 需求类型 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">需求类型</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in demandTypes"
            :key="idx"
            class="inline-flex items-center rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="!demandTypes || demandTypes.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>

      <!-- 业务场景 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">业务场景</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in businessScenarios"
            :key="idx"
            class="inline-flex items-center rounded-full bg-green-500/10 text-green-400 border border-green-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="!businessScenarios || businessScenarios.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>

      <!-- 痛点 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">痛点</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in painPoints"
            :key="idx"
            class="inline-flex items-center rounded-full bg-red-500/10 text-red-400 border border-red-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="!painPoints || painPoints.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>

      <!-- 产品品类 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">产品品类</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in productCategories"
            :key="idx"
            class="inline-flex items-center rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="!productCategories || productCategories.length === 0" class="text-xs text-[var(--muted)]">-</span>
        </div>
      </div>
    </div>
  </div>
</template>
