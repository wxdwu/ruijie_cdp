<script setup>
import PrototypeChart from './PrototypeChart.vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  opportunities: { type: Array, default: () => [] },
})

const healthAxes = ['拜访活跃', '有效拜访', '漏斗厚度', '赢率', '成交体量']
const funnelRows = ['漏斗内 · 本客户', '漏斗内 · 同行均值', '漏斗外 · 本客户', '漏斗外 · 同行均值']
const stages = ['MQL', 'SQL', '方案', '投标', '谈判', '成交']
const help = {
  health: {
    title: '经营健康度对位',
    type: 'calc',
    fields: [
      {
        variable: '拜访活跃 / 有效拜访',
        meaning: '客户拜访活跃度与有效拜访情况。',
        sourceTable: 'ods_crm_contact_day',
        sourceField: 'ods_crm_contact_day.last_visit_time, ods_crm_contact_day.not_visit_days',
        calculation: '用最近拜访时间和未拜访天数判断拜访活跃；有效拜访次数当前未聚合，先标记待补。',
        emptyState: '无拜访数据时显示 0 或待聚合。',
        type: 'calc',
      },
      {
        variable: '漏斗厚度 / 成交体量',
        meaning: '客户在途商机金额、漏斗商机数量和成交金额。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.active_opp_amount, dws_customer_360.funnel_opp_count, dws_customer_360.won_amount, ods_crm_opportunity_day.amount_10k, ods_crm_opportunity_day.actual_order_amount_10k',
        calculation: 'DWS 取客户聚合金额；ODS 明细按未取消/丢单、活动中和成交金额补充口径。',
        emptyState: '无商机或成交时显示 0。',
        type: 'calc',
      },
    ],
  },
  funnelAmount: {
    title: '漏斗金额 · 同行对位',
    type: 'calc',
    fields: [
      {
        variable: '漏斗金额',
        meaning: '客户漏斗内/在途商机金额以及漏斗外金额对比。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.active_opp_amount, dws_customer_360.funnel_opp_count, ods_crm_opportunity_day.amount_10k, ods_crm_opportunity_day.is_funnel, ods_crm_opportunity_day.is_active, ods_crm_opportunity_day.is_cancel_lost',
        calculation: 'active_opp_amount 承接在途金额；is_funnel=是计入漏斗内。漏斗外金额 sumMoneyOutFunnel__c 当前未入库。',
        emptyState: '无金额时显示 0；同行均值和漏斗外金额显示待聚合。',
        type: 'calc',
      },
    ],
  },
  stageStack: {
    title: '商机阶段堆积',
    type: 'calc',
    fields: [
      {
        variable: '阶段金额',
        meaning: '按商机阶段累计金额，观察漏斗厚度。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.purchase_stage, dws_customer_360.forecast_type, dws_customer_360.highest_stage_opp, ods_crm_opportunity_day.customer_stage, ods_crm_opportunity_day.forecast_type, ods_crm_opportunity_day.amount_10k',
        calculation: '优先按 customer_stage 映射 MQL/SQL/方案/投标/谈判/成交，缺省回退 forecast_type，并按 amount_10k 累计。',
        emptyState: '无商机阶段时显示暂无数据。',
        type: 'calc',
      },
    ],
  },
  businessInsight: {
    title: 'AI 业务洞察',
    type: 'calc',
    fields: [
      {
        variable: '业务洞察输入',
        meaning: '用于生成经营差距、阶段聚集和赢率判断的字段集合。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day, dws_interaction_detail',
        sourceField: 'dws_customer_360.intent_level, dws_customer_360.interaction_count_total, dws_customer_360.active_opp_count, dws_customer_360.active_opp_amount, dws_customer_360.won_amount, ods_crm_opportunity_day.win_rate, ods_crm_opportunity_day.expect_order_date, ods_crm_opportunity_day.cancel_reason, dws_interaction_detail.event_time',
        calculation: '只基于已给定字段输出结论；同行基准、阻塞点、有效拜访字段当前标记待聚合。',
        emptyState: '缺少字段时展示暂无对比或待聚合。',
        type: 'calc',
      },
    ],
  },
}
function pick(...keys) {
  for (const key of keys) {
    const value = props.customer?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function numberValue(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function formatWan(value) {
  let number = numberValue(value)
  if (Math.abs(number) >= 10000) number = number / 10000
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}万`
}

function wonRate() {
  if (!props.opportunities.length) return 0
  const won = props.opportunities.filter(item => (
    numberValue(item.actual_order_amount_10k) > 0 ||
    numberValue(item.win_rate) >= 100 ||
    ['成交', '赢单', '100%'].includes(String(item.stage || item.customer_stage || item.forecast_type || item.win_rate))
  )).length
  return Math.round((won / props.opportunities.length) * 100)
}

function activeOppAmountWan() {
  return formatWan(pick('sumMoneyInFunnel__c', 'active_opp_amount'))
}
</script>

<template>
  <div class="prototype-tab">
    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2>经营健康度对位<FieldHelpTooltip :help="help.health" /></h2><p>五维拉通本客户与同行业基准</p></div><span>Peer Radar</span></header>
        <div class="prototype-body"><PrototypeChart type="radar" :labels="healthAxes" :height="310" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2>漏斗金额 · 同行对位<FieldHelpTooltip :help="help.funnelAmount" align="end" /></h2><p>在/外漏斗金额对比同行均值</p></div><span>Funnel</span></header>
        <div class="prototype-body"><PrototypeChart type="bar" :labels="funnelRows" unit="万" :height="310" /></div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>商机阶段堆积<FieldHelpTooltip :help="help.stageStack" /></h2><p>各阶段金额（万）累计，越厚=漏斗越健康</p></div><span>Pipeline</span></header>
      <div class="prototype-body"><PrototypeChart type="stack" :labels="stages" unit="万" :height="245" /></div>
    </section>

    <section class="prototype-panel">
      <header><div><h2>AI 业务洞察<FieldHelpTooltip :help="help.businessInsight" align="end" /></h2><p>基于本客户与同行字段的差距分析</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>漏斗内/在途金额 <b>{{ activeOppAmountWan() }}</b>，<span>同行均值字段暂缺</span>。</p>
        <p>总拜访 <b>{{ pick('visitTotalCount', 'visit_total_count') || 0 }}</b> 次（有效 {{ pick('effectiverecord__c', 'effective_record_count') || 0 }}），无拜访天数 {{ pick('noVisitDays__c', 'no_visit_days') || 0 }} 天。</p>
        <p>商机赢率 <b>{{ wonRate() }}%</b>，<span>暂无同行对比</span>。</p>
        <p>商机最聚集阶段：<b>{{ pick('highest_stage_opp', 'forecast_type') || '暂无数据' }}</b>。</p>
      </div>
    </section>
  </div>
</template>
