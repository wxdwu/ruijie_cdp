<script setup>
import KpiCards from './KpiCards.vue'
import CustomerProfileOverview from './CustomerProfileOverview.vue'
import BehaviorTimeline from './BehaviorTimeline.vue'
import AiInsight from './AiInsight.vue'

defineProps({
  customer: { type: Object, default: () => ({}) },
  interactions: { type: Array, default: () => [] },
  aiInsight: { type: Object, default: () => ({}) },
  priorityRecommendations: { type: Array, default: () => [] },
  opportunities: { type: Array, default: () => [] },
  customerStatistics: { type: Object, default: () => ({}) },
})
</script>

<template>
  <div class="space-y-6">
    <!-- KPI Cards -->
    <KpiCards
      :intent="customer.intent_level"
      :interaction-count="customer.interaction_count_30d || 0"
      :stage="customer.purchase_stage"
      :key-roles="customer.role_coverage"
      :opportunity-count="opportunities?.length || 0"
    />

    <!-- Customer profile and AI insight -->
    <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <CustomerProfileOverview
        class="h-full"
        :customer="customer"
        :customer-statistics="customerStatistics"
        :opportunities="opportunities"
      />
      <AiInsight
        class="h-full"
        :business-conclusion="aiInsight.business_conclusion"
        :top-contacts="aiInsight.contact_insights"
        :priority-contacts="priorityRecommendations"
        :evidence-chain="aiInsight.evidence"
      />
    </div>

    <!-- Interaction timeline -->
    <BehaviorTimeline :interactions="interactions" />
  </div>
</template>
