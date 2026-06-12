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

    <!-- Two Column Layout -->
    <div class="grid grid-cols-2 gap-6">
      <!-- Left Column -->
      <div class="space-y-6">
        <CustomerProfile
          :industry="customer.industry"
          :region="customer.region"
          :owner="customer.owner_name"
          :telecom-address="customer.region"
          :is-existing-customer="customer.is_existing_customer"
        />
        <BusinessTags
          :demand-types="customer.product_categories"
          :business-scenarios="customer.industry"
          :pain-points="[]"
          :product-categories="customer.product_categories"
        />
      </div>

      <!-- Right Column -->
      <div class="space-y-6">
        <FollowupStatus
          :last-interaction="customer.last_interaction_time"
          :preferred-channels="customer.top_channels"
        />
        <OpportunityBudget
          :funnel-count="customer.funnel_opp_count || 0"
          :highest-stage="customer.forecast_type || '-'"
          :recent-deals="customer.won_amount"
        />
      </div>
    </div>

    <!-- Bottom Section -->
    <div class="grid grid-cols-2 gap-6">
      <BehaviorTimeline :interactions="interactions" />
      <AiInsight
        :business-conclusion="aiInsight.business_conclusion"
        :top-contacts="aiInsight.contact_insights"
        :evidence-chain="aiInsight.evidence"
      />
    </div>
  </div>
</template>
