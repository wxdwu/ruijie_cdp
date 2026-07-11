<script setup>
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  customerStatistics: { type: Object, default: () => ({}) },
  interactions: { type: Array, default: () => [] },
  opportunities: { type: Array, default: () => [] },
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

function uniqueList(values) {
  return [...new Set(values.map(item => String(item || '').trim()).filter(Boolean))]
}

function pick(...keys) {
  for (const key of keys) {
    const value = props.customer?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function display(...keys) {
  const value = pick(...keys)
  return value === null ? '—' : value
}

function formatBool(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (value === true || value === 1 || value === '1' || value === '是' || value === 'Y') return '是'
  if (value === false || value === 0 || value === '0' || value === '否' || value === 'N') return '否'
  return value
}

function formatYuan(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} 元`
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const channelLabels = {
  email: '邮件',
  web: '官网',
  event: '直播/活动',
  wechat: '微信',
}

function preferredChannels() {
  const counts = new Map()
  props.interactions.forEach(item => {
    const channel = item?.channel || item?.interaction_channel || item?.last_interaction_channel
    if (!channel) return
    counts.set(channel, (counts.get(channel) || 0) + 1)
  })
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), 'zh-CN'))
    .slice(0, 2)
    .map(([channel]) => channelLabels[channel] || channel)
}

function interactionTotal() {
  const value = props.customerStatistics?.interaction_count_total
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function addressText() {
  const parts = [
    pick('BillingState__c', 'billing_state', 'province'),
    pick('BillingCity__c', 'billing_city', 'city'),
    pick('address', 'billing_address', 'detail_address'),
  ].filter(Boolean)
  return parts.join(' ') || '—'
}

function opportunityValues(...keys) {
  const values = []
  props.opportunities.forEach(item => {
    keys.forEach(key => {
      const value = item?.[key]
      if (Array.isArray(value)) values.push(...value)
      else if (value !== null && value !== undefined && value !== '') values.push(value)
    })
  })
  return uniqueList(values)
}

function businessTagItems() {
  const demandValues = uniqueList([
    ...normalizeList(pick('demandType', 'demand_type')),
    ...opportunityValues('business_type'),
  ])
  const scenarioValues = uniqueList([
    pick('businessScenario', 'business_scenario'),
    props.customer.campaign_tag || '企业彩光ICT',
  ])
  const painValues = uniqueList([
    ...normalizeList(pick('painPoints', 'pain_points')),
  ])
  const historyProductValues = uniqueList([
    ...normalizeList(pick('historyProductLines', 'history_product_lines', 'product_categories')),
    ...opportunityValues('order_product_line'),
  ])

  return [
    { label: '需求类型', value: demandValues.join('、') || '暂无数据', empty: !demandValues.length },
    { label: '业务场景', value: scenarioValues.join('、') || '企业彩光ICT', empty: false },
    { label: '痛点', value: painValues.join('、') || '暂无数据', empty: !painValues.length },
    { label: '历史下单产品线', value: historyProductValues.join('、') || '暂无数据', empty: !historyProductValues.length },
  ]
}

const help = {
  baseInfo: {
    title: '基础信息',
    type: 'src',
    meaning: '客户360基础主档信息，用于识别客户主体、所属区域、负责人和基础状态。',
    sourceTables: 'dws_customer_360',
    sourceFields: 'dws_customer_360.customer_name, dws_customer_360.industry, dws_customer_360.region, dws_customer_360.owner_name, dws_customer_360.intent_score, dws_customer_360.intent_level, dws_customer_360.is_existing_customer',
    calculation: '页面基础信息优先读取 dws_customer_360 已聚合字段；统一社会信用代码、通讯地址、必跟状态如当前数据未写入则显示空值。',
    emptyState: '源字段为空时显示 —。',
  },
  businessTags: {
    title: '业务标签',
    fields: [
      {
        type: 'calc',
        variable: 'demand_type',
        meaning: '需求类型',
        sourceTable: 'ods_crm_opportunity_day',
        sourceFieldDisplay: 'business_type(业务类型)',
        calculation: '优先读取客户商机明细中的 business_type 去重展示。',
        emptyState: '无数据时显示暂无数据。',
      },
      {
        type: 'calc',
        variable: 'business_scenario',
        meaning: '业务场景',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'campaign_tag(专项标签)',
        calculation: '当前业务场景按专项标签展示，默认企业彩光ICT。',
        emptyState: '无数据时显示企业彩光ICT。',
      },
      {
        type: 'calc',
        variable: 'pain_points',
        meaning: '痛点',
        sourceTable: '-',
        sourceFieldDisplay: '-',
        calculation: '当前数据库未找到稳定痛点字段。',
        emptyState: '无数据时显示暂无数据。',
      },
      {
        type: 'calc',
        variable: 'history_product_lines',
        meaning: '历史下单产品线',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceFieldDisplay: 'product_categories(历史下单产品线), order_product_line(订单产品线名称)',
        calculation: '优先读取 dws_customer_360.product_categories；为空时取商机明细 order_product_line 去重展示。',
        emptyState: '无数据时显示暂无数据。',
      },
    ],
  },
  followup: {
    title: '跟进状态',
    fields: [
      {
        type: 'src',
        variable: 'last_interaction_time',
        meaning: '最近互动',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'last_interaction_time(最近互动时间)',
        calculation: '-',
        emptyState: '无互动时显示 —。',
      },
      {
        type: 'src',
        variable: 'last_visit_time',
        meaning: '最近拜访',
        sourceTable: 'ods_crm_contact_day',
        sourceFieldDisplay: 'last_visit_time(最新拜访时间)',
        calculation: '按客户取 MAX(last_visit_time)。',
        emptyState: '无拜访时显示 —。',
      },
      {
        type: 'calc',
        variable: 'interaction_count_total',
        meaning: '累计 / 有效',
        sourceTable: 'api/customers/statistics/by-name',
        sourceFieldDisplay: 'interaction_count_total(总互动数量)',
        calculation: '累计和有效本轮均按 interaction_count_total 展示；计划暂无数据源，固定显示 0。',
        emptyState: '无数据时显示 0 / 0 / 0。',
      },
      {
        type: 'calc',
        variable: 'preferred_channels',
        meaning: '偏好渠道',
        sourceTable: 'dws_interaction_detail',
        sourceFieldDisplay: 'channel(互动渠道)',
        calculation: '按当前客户互动明细 channel 分组计数，取互动次数最多的前两种渠道。',
        emptyState: '无互动渠道时显示 —。',
      },
    ],
  },
  opportunityBudget: {
    title: '商机与预算',
    fields: [
      {
        type: 'src',
        variable: 'funnel_opp_count',
        meaning: '漏斗内商机数',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'funnel_opp_count(漏斗内商机数)',
        calculation: '-',
        emptyState: '无数据时显示 0。',
      },
      {
        type: 'src',
        variable: 'active_opp_amount',
        meaning: '商机金额',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'active_opp_amount(在途商机总金额)',
        calculation: '-',
        emptyState: '无数据时显示 0 元。',
      },
      {
        type: 'src',
        variable: 'forecast_type',
        meaning: '最高阶段商机',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'highest_stage_opp(最高阶段商机快照), forecast_type(预测类别)',
        calculation: '优先展示 highest_stage_opp；为空时展示 forecast_type。',
        emptyState: '无数据时显示 —。',
      },
      {
        type: 'src',
        variable: 'product_budget',
        meaning: '产品预算',
        sourceTable: '-',
        sourceFieldDisplay: '-',
        calculation: '当前 dws 表未找到稳定产品预算金额字段，先显示空值。',
        emptyState: '无字段时显示字段待填充。',
      },
      {
        type: 'src',
        variable: 'won_amount',
        meaning: '近2年成交',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'won_amount(近2年成交金额)',
        calculation: '-',
        emptyState: '无数据时显示 0 元。',
      },
      {
        type: 'src',
        variable: 'history_win',
        meaning: '历史成交金额',
        sourceTable: '-',
        sourceFieldDisplay: '-',
        calculation: '当前 dws 表未找到稳定历史成交金额字段，先显示空值。',
        emptyState: '无字段时显示字段待填充。',
      },
    ],
  },
}
</script>

<template>
  <div class="profile-overview rounded-xl border border-[var(--line)] bg-[var(--panel)]">
    <div class="panel-heading">
      <div>
        <span class="text-sm font-semibold text-[var(--text)]">客户档案</span>
        <span class="ml-2 text-[10px] font-semibold tracking-widest text-[var(--muted)]">PROFILE</span>
      </div>
      <span class="text-xs text-[var(--muted)]">基础信息 · 业务标签 · 偏好渠道</span>
    </div>

    <div class="space-y-5 p-5">
      <section class="profile-block">
        <div class="mb-4 flex items-center justify-between">
          <div class="section-title">基础信息<FieldHelpTooltip :help="help.baseInfo" /></div>
          <span class="customer-type">
            {{ customer.is_existing_customer ? '存量客户' : '新客户' }}
          </span>
        </div>
        <div class="grid grid-cols-2 gap-x-8 gap-y-4">
          <div class="profile-field">
            <span>行业 / 区域</span>
            <strong>{{ customer.industry || '—' }} · {{ customer.region || '—' }}</strong>
          </div>
          <div class="profile-field">
            <span>负责人</span>
            <strong>{{ customer.owner_name || '—' }}</strong>
          </div>
          <div class="profile-field demo-missing-field" data-demo-missing="缺原始字段：统一社会信用代码">
            <span>统一社会信用代码</span>
            <strong>{{ display('UniformSocialCreditCode__c', 'uniform_social_credit_code', 'social_credit_code') }}</strong>
          </div>
          <div class="profile-field demo-missing-field" data-demo-missing="需规则计算：必跟标签">
            <span>必跟 / 老客户</span>
            <strong>
              {{ formatBool(pick('MustFollow__c', 'must_follow')) }} /
              {{ formatBool(pick('IsOldAccount__c', 'is_old_account', 'is_existing_customer')) }}
            </strong>
          </div>
          <div class="profile-field demo-missing-field" data-demo-missing="缺原始字段：企业通讯地址">
            <span>通讯地址</span>
            <strong>{{ addressText() }}</strong>
          </div>
          <div class="profile-field">
            <span>合作意向</span>
            <strong>{{ customer.intent_level || '—' }} · {{ customer.intent_score ?? 0 }} 分</strong>
          </div>
        </div>
      </section>

      <section class="demo-missing-field" data-demo-missing="缺需求/场景/痛点字段；需聚合历史产品">
        <div class="section-title mb-3">业务标签<FieldHelpTooltip :help="help.businessTags" /></div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="item in businessTagItems()"
            :key="item.label"
            class="business-tag"
            :class="{ 'business-tag--empty': item.empty }"
          >
            <b>{{ item.label }}</b>
            <span>{{ item.value }}</span>
          </span>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-6 border-t border-[var(--line)] pt-5 md:grid-cols-2">
        <section>
          <div class="section-title mb-3">跟进状态<FieldHelpTooltip :help="help.followup" /></div>
          <div class="compact-list">
            <div><span>最近互动</span><strong>{{ formatTime(pick('recentActivityRecordTime', 'last_interaction_time')) }}</strong></div>
            <div><span>最近拜访</span><strong>{{ formatTime(pick('lastVisitTime__c', 'last_visit_time')) }}</strong></div>
            <div class="demo-missing-field" data-demo-missing="缺计划字段；需规则计算有效跟进">
              <span>累计 / 计划 / 有效</span>
              <strong>
                {{ interactionTotal() }} / 0 / {{ interactionTotal() }}
              </strong>
            </div>
            <div>
              <span>偏好渠道</span>
              <strong>{{ preferredChannels().join('、') || '—' }}</strong>
            </div>
          </div>
        </section>

        <section>
          <div class="section-title mb-3">商机 &amp; 预算<FieldHelpTooltip :help="help.opportunityBudget" align="end" /></div>
          <div class="compact-list">
            <div>
              <span>漏斗内</span>
              <strong>
                {{ display('countInsideFunnel__c', 'funnel_opp_count') }} 项 /
                {{ formatYuan(pick('active_opp_amount')) }}
              </strong>
            </div>
            <div><span>最高阶段商机</span><strong>{{ display('highest_stage_opp', 'forecast_type') }}</strong></div>
            <div class="demo-missing-field" data-demo-missing="缺原始字段：产品预算"><span>产品预算</span><strong><span class="missing-field-tag">字段待填充</span></strong></div>
            <div class="demo-missing-field" data-demo-missing="需按成交明细聚合历史金额">
              <span>近2年成交 / 历史</span>
              <strong>
                {{ formatYuan(pick('won_amount')) }} /
                <span class="missing-field-tag">字段待填充</span>
              </strong>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-overview {
  overflow: visible;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  background: rgba(79, 172, 254, 0.04);
}

.profile-block {
  padding: 15px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(79, 172, 254, 0.035);
}

.section-title {
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.customer-type,
.business-tag {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  font-size: 11px;
}

.customer-type {
  padding: 3px 9px;
}

.business-tag {
  gap: 5px;
  padding: 4px 9px;
  background: rgba(79, 172, 254, 0.06);
}

.business-tag b {
  color: var(--text);
  font-weight: 700;
}

.business-tag--empty {
  background: rgba(159, 176, 208, 0.06);
}

.business-tag--empty span {
  color: var(--muted);
}

.missing-field-tag {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(248, 113, 113, 0.50);
  border-radius: 999px;
  background: rgba(248, 113, 113, 0.10);
  color: rgb(220, 38, 38);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.375;
}

.profile-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.profile-field span,
.compact-list span,
.empty-text {
  color: var(--muted);
  font-size: 12px;
}

.profile-field strong,
.compact-list strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.compact-list {
  display: flex;
  flex-direction: column;
}

.compact-list > div {
  display: flex;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px dashed var(--line);
}

.compact-list > div:last-child {
  border-bottom: 0;
}

.compact-list strong {
  text-align: right;
}

@media (max-width: 640px) {
  .panel-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
