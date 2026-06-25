<script setup>
import { defineAsyncComponent, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { customerApi } from '../api'
import OverviewTab from '../components/detail/OverviewTab.vue'
import ContactsTab from '../components/detail/ContactsTab.vue'

const BusinessFunnelTab = defineAsyncComponent(() => import('../components/detail/BusinessFunnelTab.vue'))
const BudgetOutputTab = defineAsyncComponent(() => import('../components/detail/BudgetOutputTab.vue'))
const RiskComplianceTab = defineAsyncComponent(() => import('../components/detail/RiskComplianceTab.vue'))
const OpportunitiesTab = defineAsyncComponent(() => import('../components/detail/OpportunitiesTab.vue'))

const route = useRoute()
const customerId = route.params.id

const activeTab = ref('overview')
const loading = ref(true)
const customer = ref({})
const interactions = ref([])
const contacts = ref([])
const aiInsight = ref({})
const opportunities = ref([])
const customerStatistics = ref({})
const priorityRecommendation = ref(null)
const priorityRecommendations = ref([])
const recommendSource = ref('rule')

const tabs = [
  { key: 'overview', label: '概览' },
  { key: 'contacts', label: '联系人' },
  { key: 'business', label: '经营&漏斗' },
  { key: 'budget', label: '预算&产出' },
  { key: 'risk', label: '风险&合规' },
  { key: 'opportunities', label: '商机' },
]

async function fetchAllData() {
  loading.value = true
  try {
    const results = await Promise.allSettled([
      customerApi.get(customerId),
      customerApi.contacts(customerId),
      customerApi.interactions(customerId),
      customerApi.opportunities(customerId),
      customerApi.aiInsight(customerId),
    ])

    const valueAt = (index, fallback) => results[index].status === 'fulfilled'
      ? results[index].value
      : fallback
    const detailRes = valueAt(0, {})
    const contactsRes = valueAt(1, [])
    const interactionsRes = valueAt(2, [])
    const oppsRes = valueAt(3, [])
    const aiRes = valueAt(4, {})

    customer.value = detailRes
    contacts.value = Array.isArray(contactsRes) ? contactsRes : (contactsRes.contacts || [])
    interactions.value = Array.isArray(interactionsRes) ? interactionsRes : (interactionsRes.interactions || [])
    opportunities.value = Array.isArray(oppsRes) ? oppsRes : (oppsRes.opportunities || [])
    aiInsight.value = aiRes
    const recommendations = aiRes.recommendations || aiRes.candidates || []
    const singleRecommendation = aiRes.recommendation || recommendations[0] || null
    priorityRecommendation.value = singleRecommendation
    priorityRecommendations.value = recommendations.length
      ? recommendations
      : (singleRecommendation ? [singleRecommendation] : [])
    recommendSource.value = aiRes.source || 'rule'
    results.forEach((result, index) => {
      if (result.status === 'rejected') console.warn(`customer detail request ${index} failed`, result.reason)
    })

    if (customer.value.customer_name) {
      customerApi.statisticsByName(customer.value.customer_name).then(statisticsRes => {
        customerStatistics.value = statisticsRes?.status === 'success'
          ? (statisticsRes.data || {})
          : {}
      }).catch(error => {
        customerStatistics.value = {}
        console.warn('customer statistics request failed', error)
      })
    }
  } catch (e) {
    console.error('fetchAllData', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchAllData()
})
</script>

<template>
  <div class="min-h-screen bg-[var(--bg)] text-[var(--text)]">
    <!-- Header -->
    <div class="border-b border-[var(--line)] bg-[var(--panel)] px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <div>
            <h1 class="text-xl font-semibold text-[var(--text)]">{{ customer.customer_name || '加载中...' }}</h1>
            <div class="flex items-center gap-3 mt-1">
              <span class="text-xs px-2 py-0.5 rounded bg-[var(--brand)]/10 text-[var(--brand)]">
                {{ customer.campaign_tag || '-' }}
              </span>
              <span class="text-xs text-[var(--muted)]">{{ customer.industry }}</span>
              <span class="text-xs text-[var(--muted)]">|</span>
              <span class="text-xs text-[var(--muted)]">{{ customer.region }}</span>
              <span class="text-xs text-[var(--muted)]">|</span>
              <span class="text-xs text-[var(--muted)]">客户经理: {{ customer.owner_name }}</span>
              <span class="text-xs text-[var(--muted)]">|</span>
              <span class="text-xs text-[var(--muted)]">采购阶段: {{ customer.purchase_stage || '-' }}</span>
              <span class="text-xs text-[var(--muted)]">|</span>
              <span class="text-xs text-[var(--muted)]">销售阶段: {{ customer.forecast_type || customer.highest_stage_opp || '-' }}</span>
            </div>
          </div>
        </div>
        <div class="text-right">
          <div class="text-xs text-[var(--muted)]">最近互动</div>
          <div class="text-sm text-[var(--text)]">{{ customer.last_interaction_time || '-' }}</div>
        </div>
      </div>

      <!-- Tab Navigation -->
      <div class="c360-tabs mt-4 flex gap-10 overflow-x-auto">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          @click="activeTab = tab.key"
          class="shrink-0 border-b-2 pb-2 text-sm font-medium transition-colors"
          :class="
            activeTab === tab.key
              ? 'text-[var(--brand)] border-[var(--brand)]'
              : 'text-[var(--muted)] border-transparent hover:text-[var(--text)]'
          "
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="p-6">
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="flex items-center gap-2 text-[var(--muted)]">
          <span class="animate-spin">⏳</span>
          加载中...
        </div>
      </div>

      <OverviewTab
        v-else-if="activeTab === 'overview'"
        :customer="customer"
        :contacts="contacts"
        :interactions="interactions"
        :ai-insight="aiInsight"
        :priority-recommendations="priorityRecommendations"
        :opportunities="opportunities"
        :customer-statistics="customerStatistics"
      />

      <ContactsTab
        v-else-if="activeTab === 'contacts'"
        :contacts="contacts"
        :recommendation="priorityRecommendation"
        :recommendations="priorityRecommendations"
        :recommend-source="recommendSource"
      />

      <BusinessFunnelTab
        v-else-if="activeTab === 'business'"
        :customer="customer"
        :opportunities="opportunities"
      />

      <BudgetOutputTab
        v-else-if="activeTab === 'budget'"
        :customer="customer"
      />

      <RiskComplianceTab
        v-else-if="activeTab === 'risk'"
        :customer="customer"
      />

      <OpportunitiesTab
        v-else-if="activeTab === 'opportunities'"
        :customer="customer"
        :opportunities="opportunities"
      />
    </div>
  </div>
</template>
