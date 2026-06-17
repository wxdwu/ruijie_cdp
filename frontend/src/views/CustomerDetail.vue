<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { customerApi } from '../api'
import OverviewTab from '../components/detail/OverviewTab.vue'
import ContactsTab from '../components/detail/ContactsTab.vue'

const route = useRoute()
const customerId = route.params.id

const activeTab = ref('overview')
const loading = ref(true)
const customer = ref({})
const interactions = ref([])
const contacts = ref([])
const aiInsight = ref({})
const opportunities = ref([])
const priorityRecommendations = ref([])
const recommendSource = ref('rule')

async function fetchAllData() {
  loading.value = true
  try {
    const [
      detailRes, contactsRes, interactionsRes,
      oppsRes, aiRes, priorityRes
    ] = await Promise.all([
      customerApi.get(customerId),
      customerApi.contacts(customerId),
      customerApi.interactions(customerId),
      customerApi.opportunities(customerId),
      customerApi.aiInsight(customerId),
      customerApi.priorityContact(customerId),
    ])

    customer.value = detailRes
    contacts.value = Array.isArray(contactsRes) ? contactsRes : (contactsRes.contacts || [])
    interactions.value = Array.isArray(interactionsRes) ? interactionsRes : (interactionsRes.interactions || [])
    opportunities.value = Array.isArray(oppsRes) ? oppsRes : (oppsRes.opportunities || [])
    aiInsight.value = aiRes
    priorityRecommendations.value = priorityRes.recommendations || []
    recommendSource.value = priorityRes.source || 'rule'
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
            </div>
          </div>
        </div>
        <div class="text-right">
          <div class="text-xs text-[var(--muted)]">最近互动</div>
          <div class="text-sm text-[var(--text)]">{{ customer.last_interaction_time || '-' }}</div>
        </div>
      </div>

      <!-- Tab Navigation -->
      <div class="flex gap-6 mt-4">
        <button
          @click="activeTab = 'overview'"
          class="pb-2 text-sm font-medium transition-colors border-b-2"
          :class="
            activeTab === 'overview'
              ? 'text-[var(--brand)] border-[var(--brand)]'
              : 'text-[var(--muted)] border-transparent hover:text-[var(--text)]'
          "
        >
          概览
        </button>
        <button
          @click="activeTab = 'contacts'"
          class="pb-2 text-sm font-medium transition-colors border-b-2"
          :class="
            activeTab === 'contacts'
              ? 'text-[var(--brand)] border-[var(--brand)]'
              : 'text-[var(--muted)] border-transparent hover:text-[var(--text)]'
          "
        >
          联系人
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
        :interactions="interactions"
        :ai-insight="aiInsight"
        :opportunities="opportunities"
      />

      <ContactsTab
        v-else-if="activeTab === 'contacts'"
        :contacts="contacts"
        :recommendations="priorityRecommendations"
        :recommend-source="recommendSource"
      />
    </div>
  </div>
</template>
