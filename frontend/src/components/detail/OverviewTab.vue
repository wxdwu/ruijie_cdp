<script setup>
import KpiCards from './KpiCards.vue'
import CustomerProfile from './CustomerProfile.vue'
import BusinessTags from './BusinessTags.vue'
import FollowupStatus from './FollowupStatus.vue'
import OpportunityBudget from './OpportunityBudget.vue'
import BehaviorTimeline from './BehaviorTimeline.vue'
import AiInsight from './AiInsight.vue'

defineProps({
  customer: { type: Object, default: () => ({}) },
  interactions: { type: Array, default: () => [] },
  aiInsight: { type: Object, default: () => ({}) },
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

    <!-- Detail Matrix -->
    <div class="space-y-6">
      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <CustomerProfile
          class="h-full"
          :industry="customer.industry"
          :region="customer.region"
          :owner="customer.owner_name"
          :telecom-address="customer.region"
          :is-existing-customer="Boolean(customer.is_existing_customer)"
        />
        <FollowupStatus
          class="h-full"
          :last-interaction="customer.last_interaction_time"
          :preferred-channels="customer.top_channels"
          :cumulative-count="customerStatistics.interaction_count_total"
          :effective-count="customerStatistics.interaction_count_total"
        />
      </div>
      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <BusinessTags
          class="h-full"
          :demand-types="customer.product_categories"
          :business-scenarios="customer.industry"
          :pain-points="[]"
          :product-categories="customer.product_categories"
        />
        <OpportunityBudget
          class="h-full"
          :funnel-count="customer.funnel_opp_count || 0"
          :highest-stage="customer.forecast_type || '-'"
          :recent-deals="customer.won_amount"
        />
      </div>
    </div>

    <!-- Bottom Section -->
    <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <BehaviorTimeline class="h-full" :interactions="interactions" />
      <AiInsight
        class="h-full"
        :business-conclusion="aiInsight.business_conclusion"
        :top-contacts="aiInsight.contact_insights"
        :evidence-chain="aiInsight.evidence"
      />
    </div>
  </div>
</template>
