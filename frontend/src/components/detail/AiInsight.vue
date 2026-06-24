<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  opportunities: { type: Array, default: () => [] },
  businessConclusion: { type: Array, default: () => [] },
  topContacts: { type: Array, default: () => [] },
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

  return (props.topContacts || []).slice(0, 3).map(contact => ({
    name: typeof contact === 'string' ? contact : (contact.contact_name || '未命名联系人'),
  }))
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
  const opportunities = Number(evidence.opportunity_count || 0)
  const insights = [
    interactions > 0
      ? `当前记录到 ${interactions} 次互动，可结合最近互动继续判断客户活跃度。`
      : '当前暂无互动记录，客户活跃信号不足。',
    opportunities > 0
      ? `CRM 当前存在 ${opportunities} 个活跃商机，具备持续跟进基础。`
      : 'CRM 当前未记录活跃商机。',
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
    opportunity_count: '商机数',
    contact_count: '联系人',
    mobile_count: '手机号',
    last_interaction_time: '最近互动',
    last_interaction_channel: '最近渠道',
  }
  return map[key] || key
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
        <div class="insight-section-title">💡 业务结论</div>
        <div class="conclusion-panel">
          <p v-if="businessConclusion?.length" class="text-sm leading-7 text-[var(--text)]">
            {{ businessConclusion.join('；') }}
          </p>
          <p v-else class="text-sm text-[var(--muted)]">暂无业务结论</p>
        </div>
      </section>

      <section>
        <div class="insight-section-title">Focus 关键事实</div>
        <div class="focus-grid">
          <div v-for="item in focusFacts" :key="item.label">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </section>

      <section>
        <div class="insight-section-title">👥 联系人 Top3</div>
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
        <div class="insight-section-title">🏢 公司洞察</div>
        <div class="space-y-1.5">
          <p v-for="(line, idx) in companyInsights" :key="idx" class="text-sm leading-6 text-[var(--muted)]">
            {{ line }}
          </p>
        </div>
      </section>

      <section class="evidence-section">
        <button class="evidence-toggle" type="button" @click="evidenceExpanded = !evidenceExpanded">
          <span>查看证据</span>
          <span class="evidence-chevron" :class="{ expanded: evidenceExpanded }">⌄</span>
        </button>
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
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.evidence-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px;
  border: 0;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
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
