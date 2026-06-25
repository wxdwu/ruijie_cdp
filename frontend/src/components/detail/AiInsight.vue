<script setup>
import { computed, ref } from 'vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  opportunities: { type: Array, default: () => [] },
  businessConclusion: { type: Array, default: () => [] },
  priorityContacts: { type: Array, default: () => [] },
  evidenceChain: { type: Object, default: () => ({}) },
})

const evidenceExpanded = ref(false)

const contactTop3 = computed(() => {
  if (props.priorityContacts?.length) {
    return props.priorityContacts.slice(0, 3).map(contact => ({
      name: contact.contact_name || '未命名联系人',
      score: contact.relevance_score ?? contact.priority_score ?? contact.score,
      role: contact.role_category || contact.purchase_role || '',
      interactionCount: contact.interaction_count_30d ?? contact.interaction_count,
      highValueCount: contact.high_value_count,
    }))
  }

  return []
})

function normalizeList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value
  if (typeof value === 'string') {
    if (value.startsWith('[')) {
      try { return JSON.parse(value) } catch { /* fall through */ }
    }
    return value.split(',').map(item => item.trim()).filter(Boolean)
  }
  return []
}

function pick(source, ...keys) {
  for (const key of keys) {
    const value = source?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function formatWan(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}万`
}

const topOpportunity = computed(() => {
  const items = [...(props.opportunities || [])]
  if (!items.length) return null
  return items.sort((a, b) => {
    const amountA = Number(pick(a, 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan') || 0)
    const amountB = Number(pick(b, 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan') || 0)
    return amountB - amountA
  })[0]
})

const focusFacts = computed(() => {
  const topics = [
    ...normalizeList(pick(props.customer, 'product_categories', 'product_interests')),
    ...normalizeList(pick(props.customer, 'top_channels')),
  ].slice(0, 3)
  const competitors = normalizeList(pick(props.customer, 'competitors', 'main_competitors'))
  const keyRoleText = props.customer.role_coverage || ''
  const mainOpp = topOpportunity.value
  return [
    { label: '重点主题', value: topics.join('、') || '—' },
    { label: '主要竞品', value: competitors.join('、') || pick(mainOpp, 'competitor', 'competitors') || '—' },
    { label: '关键人缺口', value: keyRoleText && keyRoleText !== '全' ? keyRoleText : '无' },
    {
      label: '主商机',
      value: mainOpp
        ? `${pick(mainOpp, 'stage', 'forecast_type', 'sales_stage') || '—'} / ${formatWan(pick(mainOpp, 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan'))}`
        : '—',
    },
  ]
})

const companyInsights = computed(() => {
  const evidence = props.evidenceChain || {}
  const interactions = Number(evidence.interaction_count || 0)
  const opportunities = Number(props.customer?.funnel_opp_count || 0)
  const insights = [
    interactions > 0
      ? `当前记录到 ${interactions} 次互动，可结合最近互动继续判断客户活跃度。`
      : '当前暂无互动记录，客户活跃信号不足。',
    opportunities > 0
      ? `CRM 当前存在 ${opportunities} 个漏斗内商机，具备持续跟进基础。`
      : 'CRM 当前未记录漏斗内商机。',
  ]

  if (evidence.intent_score != null || evidence.intent_level) {
    insights.push(`当前合作意向为 ${evidence.intent_level || '未标注'}，意向分 ${evidence.intent_score ?? 0}/100。`)
  }
  return insights
})

function evidenceLabel(key) {
  const map = {
    intent_score: '意向分',
    intent_level: '意向等级',
    interaction_count: '互动次数',
    opportunity_count: '漏斗商机数',
    contact_count: '联系人',
    mobile_count: '手机号',
    last_interaction_time: '最近互动',
    last_interaction_channel: '最近渠道',
  }
  return map[key] || key
}

const help = {
  businessConclusion: {
    title: 'AI 业务结论',
    type: 'calc',
    meaning: '基于客户档案、互动、商机、联系人和风险字段生成的一段业务判断。',
    sourceTables: 'dws_customer_360, dws_contact_360, dws_interaction_detail, ods_crm_opportunity_day',
    sourceFields: 'dws_customer_360.intent_score, dws_customer_360.intent_level, dws_customer_360.funnel_opp_count, dws_customer_360.role_coverage, dws_interaction_detail.event_time, ods_crm_opportunity_day.amount',
    calculation: '当前业务结论由后端规则生成：先读取客户意向、互动和商机聚合字段，再结合联系人覆盖情况输出可解释结论。',
    emptyState: '缺少洞察数据时显示暂无业务结论。',
  },
  focusFacts: {
    title: 'AI 深度洞察 Focus',
    type: 'calc',
    meaning: '提炼重点主题、主要竞品、关键人缺口和主商机。',
    sourceTables: 'dws_customer_360, dws_contact_360, dws_interaction_detail, ods_crm_opportunity_day',
    sourceFields: 'dws_customer_360.product_categories, dws_customer_360.top_channels, dws_customer_360.role_coverage, dws_customer_360.highest_stage_opp, dws_customer_360.active_opp_amount, ods_crm_opportunity_day.forecast_type, ods_crm_opportunity_day.amount',
    calculation: '重点主题来自 product_categories 和 top_channels；关键人缺口来自 role_coverage；主商机优先使用 highest_stage_opp、forecast_type 和金额字段。',
    emptyState: '无对应信号时显示 — 或无。',
  },
  contactTop3: {
    title: 'AI 联系人洞察 Top3',
    type: 'calc',
    meaning: '推荐最值得优先推进的联系人。',
    sourceTables: 'dws_contact_360, dws_interaction_detail',
    sourceFields: 'dws_contact_360.role_category, dws_contact_360.purchase_role, dws_contact_360.interaction_count_30d, dws_contact_360.interaction_count, dws_interaction_detail.is_high_value',
    calculation: '联系人排序使用 backend/app/services/contact_recommend.py 的规则评分：角色权重、近30天互动、最近互动、信息完整度和意向等级综合计算，取评分最高的前三名。',
    emptyState: '无联系人或推荐结果时显示暂无可推荐联系人。',
  },
  companyInsight: {
    title: 'AI 公司洞察',
    type: 'calc',
    meaning: '从公司级别汇总客户活跃度、商机基础和合作意向。',
    sourceTables: 'dws_customer_360, ods_crm_opportunity_day, dws_interaction_detail',
    sourceFields: 'dws_customer_360.industry, dws_customer_360.interaction_count_30d, dws_customer_360.funnel_opp_count, dws_customer_360.active_opp_amount, dws_customer_360.won_amount, dws_customer_360.last_interaction_channel',
    calculation: '按公司维度提炼行业、互动活跃度、漏斗内商机、成交金额和最近渠道，每条输出一句可解释证据。',
    emptyState: '无互动或商机时提示活跃信号不足。',
  },
  evidence: {
    title: 'AI 证据链',
    type: 'src',
    meaning: 'AI 洞察所引用的底层字段和值。',
    sourceTables: 'dws_customer_360, dws_contact_360, dws_interaction_detail, ods_crm_opportunity_day',
    sourceFields: 'dws_customer_360.intent_score, dws_customer_360.intent_level, dws_customer_360.contact_count, dws_customer_360.mobile_count, dws_customer_360.last_interaction_time, dws_customer_360.last_interaction_channel, dws_customer_360.funnel_opp_count',
    calculation: '不生成新结论，只展开当前洞察依赖的字段和值，便于核对。',
    emptyState: '没有证据字段时显示暂无证据。',
  },
}
</script>

<template>
  <div class="ai-insight-card rounded-xl border border-[var(--brand)]/25 p-5">
    <div class="mb-4 flex items-center gap-2">
      <span class="text-lg">🧠</span>
      <span class="text-sm font-semibold text-[var(--text)]">AI 洞察</span>
    </div>

    <div class="space-y-5">
      <section>
        <div class="insight-section-title">业务结论<FieldHelpTooltip :help="help.businessConclusion" /></div>
        <div class="conclusion-panel">
          <p v-if="businessConclusion?.length" class="text-sm leading-7 text-[var(--text)]">
            {{ businessConclusion.join('；') }}
          </p>
          <p v-else class="text-sm text-[var(--muted)]">暂无业务结论</p>
        </div>
      </section>

      <section>
        <div class="focus-grid">
          <div v-for="item in focusFacts" :key="item.label">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </section>

      <section>
        <div class="insight-section-title">联系人 Top3<FieldHelpTooltip :help="help.contactTop3" /></div>
        <div v-if="contactTop3.length" class="space-y-1">
          <div v-for="(contact, idx) in contactTop3" :key="`${contact.name}-${idx}`" class="contact-row">
            <span class="contact-rank">{{ idx + 1 }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="text-sm font-medium text-[var(--text)]">{{ contact.name }}</span>
                <span v-if="contact.role" class="contact-role">{{ contact.role }}</span>
              </div>
              <div class="mt-1 text-xs text-[var(--muted)]">
                <span v-if="contact.score != null">优先级 {{ contact.score }}</span>
                <span v-if="contact.interactionCount != null"> · 近30天互动 {{ contact.interactionCount }} 次</span>
                <span v-if="contact.highValueCount != null"> · 高价值行为 {{ contact.highValueCount }} 次</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-[var(--muted)]">暂无可推荐联系人</div>
      </section>

      <section>
        <div class="insight-section-title">公司洞察<FieldHelpTooltip :help="help.companyInsight" /></div>
        <div class="space-y-1.5">
          <p v-for="(line, idx) in companyInsights" :key="idx" class="text-sm leading-6 text-[var(--muted)]">
            {{ line }}
          </p>
        </div>
      </section>

      <section class="evidence-section">
        <div class="evidence-heading">
          <div class="evidence-title">
            <button class="evidence-title-button" type="button" @click="evidenceExpanded = !evidenceExpanded">
              查看证据
            </button>
            <FieldHelpTooltip :help="help.evidence" />
          </div>
          <button class="evidence-chevron-button" type="button" aria-label="展开证据" @click="evidenceExpanded = !evidenceExpanded">
            <span class="evidence-chevron" :class="{ expanded: evidenceExpanded }">⌄</span>
          </button>
        </div>
        <div v-if="evidenceExpanded" class="evidence-content">
          <div v-for="(val, key) in evidenceChain" :key="key" class="evidence-row">
            <span>{{ evidenceLabel(key) }}</span>
            <strong>{{ val || '—' }}</strong>
          </div>
          <div v-if="Object.keys(evidenceChain).length === 0" class="text-sm text-[var(--muted)]">
            暂无证据
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.ai-insight-card {
  background:
    linear-gradient(180deg, rgba(79, 172, 254, 0.07), transparent 48%),
    var(--bg-card);
}

.insight-section-title {
  margin-bottom: 10px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.conclusion-panel {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(79, 172, 254, 0.08);
}

.focus-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px;
  padding: 12px;
  border: 1px dashed rgba(159, 176, 208, 0.24);
  border-radius: 10px;
}

.focus-grid span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}

.focus-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
}

.evidence-heading {
  position: relative;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 14px;
  background: var(--bg-secondary);
}

.evidence-title {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
}

.evidence-title-button,
.evidence-chevron-button {
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
}

.evidence-title-button {
  padding: 0;
  font-size: 13px;
  font-weight: 600;
}

.evidence-chevron-button {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.contact-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 7px 0;
}

.contact-rank {
  display: inline-flex;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(79, 172, 254, 0.14);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.contact-role {
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
  font-size: 11px;
}

.evidence-section {
  overflow: visible;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.evidence-chevron {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.evidence-chevron.expanded {
  transform: rotate(180deg);
}

.evidence-content {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.04);
}

.evidence-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-muted);
  font-size: 12px;
}

.evidence-row strong {
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
  text-overflow: ellipsis;
}

@media (max-width: 640px) {
  .evidence-content {
    grid-template-columns: 1fr;
  }
}
</style>
