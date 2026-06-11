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
      :intent="customer.intent"
      :interaction-count="customer.interactionCount || 0"
      :stage="customer.stage"
      :key-roles="customer.keyRoles"
      :opportunity-count="opportunities?.length || 0"
    />

    <!-- Two Column Layout -->
    <div class="grid grid-cols-2 gap-6">
      <!-- Left Column -->
      <div class="space-y-6">
        <CustomerProfile
          :industry="customer.industry"
          :region="customer.region"
          :owner="customer.owner"
          :telecom-address="customer.telecomAddress"
          :is-existing-customer="customer.isExistingCustomer"
        />
        <BusinessTags
          :demand-types="customer.demandTypes"
          :business-scenarios="customer.businessScenarios"
          :pain-points="customer.painPoints"
          :product-categories="customer.productCategories"
        />
      </div>

      <!-- Right Column -->
      <div class="space-y-6">
        <FollowupStatus
          :last-interaction="customer.lastInteraction"
          :preferred-channels="customer.preferredChannels"
        />
        <OpportunityBudget
          :funnel-count="opportunities?.length || 0"
          :highest-stage="opportunities?.[0]?.stage || '-'"
          :recent-deals="customer.recentDeals"
        />
      </div>
    </div>

    <!-- Bottom Section -->
    <div class="grid grid-cols-2 gap-6">
      <BehaviorTimeline :interactions="interactions" />
      <AiInsight
        :business-conclusion="aiInsight.businessConclusion"
        :top-contacts="aiInsight.topContacts"
        :evidence-chain="aiInsight.evidenceChain"
      />
    </div>
  </div>
</template>
