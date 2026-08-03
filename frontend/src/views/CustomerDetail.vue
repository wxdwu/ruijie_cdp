<script setup>
import { defineAsyncComponent, ref, onMounted, computed } from 'vue'
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

// 合并链信息（后端 get_customer_detail 已附带 merge_chain_info）；未合并/异常时给空结构，避免模板报错
const mergeInfo = computed(() => {
  const info = customer.value && customer.value.merge_chain_info
  if (!info) return { is_canonical: false, merged_count: 0, merged_members: [], merged_member_infos: [], merge_chain: [] }
  return {
    is_canonical: !!info.is_canonical,
    merged_count: info.merged_count || 0,
    merged_members: info.merged_members || [],
    merged_member_infos: info.merged_member_infos || [],
    merge_chain: info.merge_chain || [],
  }
})

// 新开标签页跳转到指定公司详情（绕过组件复用不刷新的问题，满足"新开界面"需求）
function openCustomer(id) {
  if (!id) return
  const url = `${location.origin}/customers/${id}`
  window.open(url, '_blank')
}

// 按成员名跳转：从 merged_member_infos 取对应 id 后新开标签页
function openMemberByName(name) {
  const hit = (mergeInfo.value.merged_member_infos || []).find((m) => m.name === name)
  if (hit && hit.id) openCustomer(hit.id)
}

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
      customerApi.interactions(customerId, { limit: 18 }),
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
            <h1 class="text-xl font-semibold text-[var(--text)]">
              {{ customer.customer_name || '加载中...' }}
              <span
                v-if="customer.merge_source_name"
                class="ml-1 text-sm font-normal text-[var(--muted)] align-middle"
              >
                （合并源：{{ customer.merge_source_name }}）
              </span>

              <!-- 合并信息：紧凑展示，不占用额外版面 -->
              <span
                v-if="mergeInfo && (mergeInfo.is_canonical ? mergeInfo.merged_count > 0 : mergeInfo.merge_chain.length)"
                class="ml-2 inline-flex items-center align-middle text-xs"
              >
                <!-- 最终合并者：展示合并数量，hover 看具体成员 -->
                <span
                  v-if="mergeInfo.is_canonical"
                  class="relative group inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 cursor-default"
                >
                  <span>已合并 {{ mergeInfo.merged_count }} 家</span>
                  <div
                    class="pointer-events-none absolute left-0 top-full mt-1 z-20 hidden group-hover:block
                           w-max max-w-xs rounded-md border border-[var(--line)] bg-[var(--panel)]
                           px-3 py-2 text-xs text-[var(--text)] shadow-lg"
                  >
                    <div class="mb-1 font-medium text-[var(--muted)]">合并成员：</div>
                    <div class="space-y-0.5">
                      <a
                        v-for="m in mergeInfo.merged_member_infos"
                        :key="m.name"
                        href="javascript:void(0)"
                        class="block hover:underline text-emerald-600"
                        :title="m.id ? '新开标签页查看该公司详情' : '无详情档案'"
                        @click="openCustomer(m.id)"
                      >{{ m.name }}</a>
                    </div>
                  </div>
                </span>

                <!-- 被合并者：hover 浮层展示从当前到最终合并者的逐步合并链 -->
                <span
                  v-else
                  class="relative group inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 cursor-default"
                >
                  <span>已并入「{{ mergeInfo.canonical_name }}」</span>
                  <div
                    class="pointer-events-auto absolute left-0 top-full mt-1 z-20 hidden group-hover:block
                           w-max max-w-sm rounded-md border border-[var(--line)] bg-[var(--panel)]
                           px-3 py-2 text-xs text-[var(--text)] shadow-lg"
                  >
                    <div class="mb-1 font-medium text-[var(--muted)]">合并路径：</div>
                    <div class="flex flex-wrap items-center gap-x-1 gap-y-1">
                      <template v-for="(node, idx) in mergeInfo.merge_chain" :key="idx">
                        <span v-if="node.folded" class="px-1 text-[var(--muted)]">…</span>
                        <a
                          v-else
                          href="javascript:void(0)"
                          class="hover:underline"
                          :class="node.id ? 'text-amber-600' : 'text-[var(--muted)]'"
                          :title="node.id ? '新开标签页查看该公司详情' : '无详情档案'"
                          @click="openCustomer(node.id)"
                        >{{ node.name }}</a>
                        <span v-if="idx < mergeInfo.merge_chain.length - 1" class="px-1 text-[var(--muted)]">→</span>
                      </template>
                    </div>
                  </div>
                </span>
              </span>
            </h1>
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
        :interactions-total="interactionsTotal"
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
