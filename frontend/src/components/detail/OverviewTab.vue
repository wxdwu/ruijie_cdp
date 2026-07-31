<script setup>
import { computed } from 'vue'
import KpiCards from './KpiCards.vue'
import CustomerProfileOverview from './CustomerProfileOverview.vue'
import BehaviorTimeline from './BehaviorTimeline.vue'
import AiInsight from './AiInsight.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  contacts: { type: Array, default: () => [] },
  interactions: { type: Array, default: () => [] },
  aiInsight: { type: Object, default: () => ({}) },
  priorityRecommendations: { type: Array, default: () => [] },
  opportunities: { type: Array, default: () => [] },
  customerStatistics: { type: Object, default: () => ({}) },
  interactionsTotal: { type: Number, default: 0 },
})

// 近30天互动次数：按当前日期往前30天实时统计，动态覆盖库中 ETL 旧口径
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000
const interactionCount30dDynamic = computed(() => {
  const now = Date.now()
  return (props.interactions || []).filter((it) => {
    const t = it?.event_time ? new Date(it.event_time).getTime() : NaN
    return !Number.isNaN(t) && now - t <= THIRTY_DAYS_MS
  }).length
})

// 联系人数量：优先用库中 contact_count，缺失/为 0 时用实时拉取的联系人列表长度兜底
const contactCount = computed(() => {
  const fromField = Number(props.customer?.contact_count ?? 0)
  if (fromField > 0) return fromField
  return (props.contacts || []).length
})

// 在途商机数：实时商机列表长度（存在即视为有在途商机）
const activeOppCount = computed(() => (props.opportunities || []).length)

// 新计算：合作意向分
const computedIntentScore = computed(() => {
  const i30 = interactionCount30dDynamic.value
  const raw = i30 * 2 + (activeOppCount.value > 0 ? 20 : 0) + (contactCount.value >= 3 ? 10 : contactCount.value * 3)
  return Math.min(100, raw)
})

// 新计算：合作意向等级
const computedIntentLevel = computed(() => {
  const i30 = interactionCount30dDynamic.value
  const totalInteractions = Number(props.interactionsTotal || props.interactions?.length || 0)
  if (i30 >= 10 && activeOppCount.value > 0) return '高'
  if (i30 >= 3) return '中'
  if (totalInteractions > 0) return '低'
  return '无'
})

// 意向等级取两者最大值：无 < 低 < 中 < 高
const LEVEL_RANK = { 无: 0, 低: 1, 中: 2, 高: 3 }
function higherLevel(a, b) {
  return (LEVEL_RANK[a] ?? 0) >= (LEVEL_RANK[b] ?? 0) ? a : b
}

// 展示值 = MAX(库中原始字段, 新计算逻辑)
const displayIntentScore = computed(() =>
  Math.max(Number(props.customer?.intent_score ?? 0), computedIntentScore.value),
)
const displayIntentLevel = computed(() =>
  higherLevel(props.customer?.intent_level || '无', computedIntentLevel.value),
)
</script>

<template>
  <div class="space-y-6">
    <!-- KPI Cards -->
    <KpiCards
      :intent="displayIntentLevel"
      :intent-score="displayIntentScore"
      :interaction-count="interactionCount30dDynamic"
      :stage="customer.purchase_stage"
      :key-roles="customer.role_coverage"
      :contacts="contacts"
      :opportunity-count="customer.funnel_opp_count || 0"
      :opportunity-amount="customer.active_opp_amount"
    />

    <!-- Customer profile and AI insight -->
    <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <CustomerProfileOverview
        class="h-full"
        :customer="customer"
        :customer-statistics="customerStatistics"
        :interactions="interactions"
        :opportunities="opportunities"
      />
      <AiInsight
        class="h-full"
        :customer="customer"
        :opportunities="opportunities"
        :business-conclusion="aiInsight.business_conclusion"
        :priority-contacts="priorityRecommendations"
        :evidence-chain="aiInsight.evidence"
        :intent-level="displayIntentLevel"
        :intent-score="displayIntentScore"
      />
    </div>

    <!-- Interaction timeline -->
    <BehaviorTimeline :interactions="interactions" :total="interactionsTotal" />
  </div>
</template>
