<script setup>
const props = defineProps({
  demandTypes: { type: [Array, String, null], default: () => [] },
  businessScenarios: { type: [Array, String, null], default: () => [] },
  painPoints: { type: [Array, String, null], default: () => [] },
  productCategories: { type: [Array, String, null], default: () => [] },
})

function normalize(val) {
  if (!val) return []
  if (Array.isArray(val)) return val
  if (typeof val === 'string') {
    // Try JSON array parse
    if (val.startsWith('[')) {
      try { return JSON.parse(val) } catch { /* fall through */ }
    }
    // Split by comma
    return val.split(',').map(s => s.trim()).filter(Boolean)
  }
  return []
}

const demandList = normalize(props.demandTypes)
const scenarioList = normalize(props.businessScenarios)
const painList = normalize(props.painPoints)
const categoryList = normalize(props.productCategories)
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
            v-for="(item, idx) in demandList"
            :key="idx"
            class="inline-flex items-center rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="demandList.length === 0" class="text-xs text-[var(--muted)]">暂无需求类型数据</span>
        </div>
      </div>

      <!-- 业务场景 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">业务场景</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in scenarioList"
            :key="idx"
            class="inline-flex items-center rounded-full bg-green-500/10 text-green-400 border border-green-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="scenarioList.length === 0" class="text-xs text-[var(--muted)]">暂无业务场景数据</span>
        </div>
      </div>

      <!-- 痛点 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">痛点</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in painList"
            :key="idx"
            class="inline-flex items-center rounded-full bg-red-500/10 text-red-400 border border-red-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="painList.length === 0" class="text-xs text-[var(--muted)]">暂无痛点数据</span>
        </div>
      </div>

      <!-- 产品品类 -->
      <div>
        <div class="text-xs text-[var(--muted)] mb-2">产品品类</div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="(item, idx) in categoryList"
            :key="idx"
            class="inline-flex items-center rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2.5 py-0.5 text-xs"
          >
            {{ item }}
          </span>
          <span v-if="categoryList.length === 0" class="text-xs text-[var(--muted)]">暂无产品品类数据</span>
        </div>
      </div>
    </div>
  </div>
</template>
