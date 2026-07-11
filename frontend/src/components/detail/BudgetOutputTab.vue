<script setup>
import PrototypeChart from './PrototypeChart.vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
})

const budgetAxes = ['LAN', 'WAN', '数据中心', '云桌面', '智慧教室']
const outputRows = [
  '当年无线产出 · 本客户', '当年无线产出 · 同行均值',
  '当年路由产出 · 本客户', '当年路由产出 · 同行均值',
  '当年安全产出 · 本客户', '当年安全产出 · 同行均值',
]
const missingBudgetFields = 'ProductBudget__c、LANBudget__c、WANBudget__c、DataCenterBudget__c、CloudDesktopBudget__c、SmartClassroomBudget__c'
const missingOutputFields = 'CurrentYearWirelessOutput__c、CurrentYearRouterOutput__c、CurrentYearSafeOutput__c'
const help = {
  budgetMix: {
    title: '预算结构对位',
    type: 'calc',
    fields: [
      {
        variable: '预算结构',
        meaning: '五大场景预算结构与同行均值对比。',
        sourceTable: '当前 DWS/已查 ODS 未发现',
        sourceField: missingBudgetFields,
        calculation: '原型字段当前未在 dws_customer_360、ods_crm_opportunity_day、ods_crm_contact_day、ods_marketing_lead_day 中发现，需后续从 CRM 客户主档聚合。',
        emptyState: '未接入时显示 0，并标记待聚合。',
        type: 'calc',
      },
    ],
  },
  realizeRate: {
    title: '预算兑现率',
    type: 'calc',
    fields: [
      {
        variable: '预算兑现率',
        meaning: '近2年成交金额 / 预算总盘。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.won_amount, dws_customer_360.active_opp_amount, ods_crm_opportunity_day.actual_order_amount_10k',
        calculation: 'won_amount 可作为已实现成交金额；预算总盘字段缺失时无法计算真实兑现率，展示 0%。',
        emptyState: '预算总盘为空时兑现率显示 0%。',
        type: 'calc',
      },
    ],
  },
  outputGap: {
    title: '当年产出 · 找空间',
    type: 'calc',
    fields: [
      {
        variable: '当年产出',
        meaning: '无线、路由、安全当年产出与同行均值对比。',
        sourceTable: 'ods_crm_opportunity_day',
        sourceField: 'ods_crm_opportunity_day.order_product_line, ods_crm_opportunity_day.order_amount_10k',
        calculation: `原型字段 ${missingOutputFields} 当前未聚合；可后续用订单产品线和订单金额按年度、产品线聚合。`,
        emptyState: '未聚合时显示暂无产出差距。',
        type: 'calc',
      },
    ],
  },
  budgetInsight: {
    title: 'AI 预算洞察',
    type: 'calc',
    fields: [
      {
        variable: '预算洞察输入',
        meaning: '用于判断预算差距、兑现率和漏斗覆盖的字段集合。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.active_opp_amount, dws_customer_360.won_amount, ods_crm_opportunity_day.order_amount_10k, ods_crm_opportunity_day.order_product_line, ods_crm_opportunity_day.actual_order_amount_10k',
        calculation: '当前先展示成交与在途覆盖；预算结构、同行均值、当年分产品线产出接入后再生成完整洞察。',
        emptyState: '缺少预算字段时提示当前库未发现。',
        type: 'calc',
      },
    ],
  },
  productBudget: {
    title: '产品线预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'ProductBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  historyWin: {
    title: '历史成交',
    type: 'calc',
    sourceTables: 'dws_customer_360, ods_crm_opportunity_day',
    sourceFields: 'dws_customer_360.won_amount, ods_crm_opportunity_day.actual_order_amount_10k',
    calculation: 'DWS 汇总实际下单金额；ODS 可按客户名追溯成交明细。',
    emptyState: '无成交时显示 0万。',
  },
  lanBudget: {
    title: 'LAN预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'LANBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  wanBudget: {
    title: 'WAN预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'WANBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  dataCenterBudget: {
    title: '数据中心预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'DataCenterBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  cloudDesktopBudget: {
    title: '云桌面预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'CloudDesktopBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  smartClassroomBudget: {
    title: '智慧教室预算',
    type: 'calc',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'SmartClassroomBudget__c',
    calculation: '原型 CRM 客户主档字段，当前需后续聚合。',
    emptyState: '未接入时显示 0万。',
  },
  recentWon: {
    title: '近2年成交',
    type: 'calc',
    sourceTables: 'dws_customer_360, ods_crm_opportunity_day',
    sourceFields: 'dws_customer_360.won_amount, ods_crm_opportunity_day.actual_order_amount_10k, ods_crm_opportunity_day.order_amount_10k',
    calculation: '当前 DWS 为总成交聚合；若需严格近2年，后续需按订单/实际下单日期聚合窗口。',
    emptyState: '无成交时显示 0万。',
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

function totalBudget() {
  return [
    pick('ProductBudget__c', 'product_budget'),
    pick('LANBudget__c', 'lan_budget'),
    pick('WANBudget__c', 'wan_budget'),
    pick('DataCenterBudget__c', 'data_center_budget'),
    pick('CloudDesktopBudget__c', 'cloud_desktop_budget'),
    pick('SmartClassroomBudget__c', 'smart_classroom_budget'),
  ].reduce((sum, value) => sum + numberValue(value), 0)
}

function realizedAmount() {
  return numberValue(pick('totalWonOpportunityAmount', 'won_amount', 'historyWin__c', 'history_win'))
}

function realizeRate() {
  const total = totalBudget()
  return total ? Math.round((realizedAmount() / total) * 100) : 0
}
</script>

<template>
  <div class="prototype-tab">
    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺五类预算字段；需聚合同行均值">预算结构对位<FieldHelpTooltip :help="help.budgetMix" /></h2><p>五大场景预算 vs 同行</p></div><span>Budget Mix</span></header>
        <div class="prototype-body"><PrototypeChart type="radar" :labels="budgetAxes" unit="万" :height="310" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2>预算兑现率<FieldHelpTooltip :help="help.realizeRate" align="end" /></h2><p>近2年成交 / 预算总盘</p></div><span>Realize Rate</span></header>
        <div class="prototype-body">
          <div class="rate-display"><b>{{ realizeRate() }}%</b><span class="prototype-badge">暂无对比</span><span>同行均值 0%</span></div>
          <p class="prototype-note">预算总盘 {{ formatWan(totalBudget()) }} ｜ 已实现 {{ formatWan(realizedAmount()) }} ｜ 当年漏斗 {{ formatWan(pick('sumMoneyInFunnel__c', 'active_opp_amount')) }}</p>
          <div class="budget-kv">
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：产品线预算">产品线预算<FieldHelpTooltip :help="help.productBudget" /></span><b>{{ formatWan(pick('ProductBudget__c', 'product_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="需按成交明细聚合">历史成交<FieldHelpTooltip :help="help.historyWin" align="end" /></span><b>{{ formatWan(pick('historyWin__c', 'history_win')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：LAN预算">LAN预算<FieldHelpTooltip :help="help.lanBudget" /></span><b>{{ formatWan(pick('LANBudget__c', 'lan_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：WAN预算">WAN预算<FieldHelpTooltip :help="help.wanBudget" align="end" /></span><b>{{ formatWan(pick('WANBudget__c', 'wan_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：数据中心预算">数据中心预算<FieldHelpTooltip :help="help.dataCenterBudget" /></span><b>{{ formatWan(pick('DataCenterBudget__c', 'data_center_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：云桌面预算">云桌面预算<FieldHelpTooltip :help="help.cloudDesktopBudget" align="end" /></span><b>{{ formatWan(pick('CloudDesktopBudget__c', 'cloud_desktop_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：智慧教室预算">智慧教室预算<FieldHelpTooltip :help="help.smartClassroomBudget" /></span><b>{{ formatWan(pick('SmartClassroomBudget__c', 'smart_classroom_budget')) }}</b></div>
            <div><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="需按日期聚合近2年成交">近2年成交<FieldHelpTooltip :help="help.recentWon" align="end" /></span><b>{{ formatWan(pick('totalWonOpportunityAmount', 'won_amount')) }}</b></div>
          </div>
        </div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="需按订单产品线聚合当年产出">当年产出 · 找空间<FieldHelpTooltip :help="help.outputGap" /></h2><p>无线 / 路由 / 安全 当年产出 vs 同行均值</p></div><span>Output vs Peers</span></header>
      <div class="prototype-body"><PrototypeChart type="bar" :labels="outputRows" unit="万" :height="270" /></div>
    </section>

    <section class="prototype-panel">
      <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺预算字段；需聚合产出">AI 预算洞察<FieldHelpTooltip :help="help.budgetInsight" align="end" /></h2><p>差距/重点/兑现率综合判定</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>当前暂无可识别的产出差距，等待无线、路由与安全产出字段接入或从订单产品线聚合。</p>
        <p>本客户产品线预算字段：<b>未在当前 DWS/已查 ODS 中发现</b>。</p>
        <p>预算总盘 <b>{{ formatWan(totalBudget()) }}</b>，近2年成交 <b>{{ formatWan(realizedAmount()) }}</b>，兑现率 <b>{{ realizeRate() }}%</b>。</p>
        <p>漏斗内金额覆盖预算 <b>{{ totalBudget() ? Math.round(numberValue(pick('sumMoneyInFunnel__c', 'active_opp_amount')) / totalBudget() * 100) : 0 }}%</b>。</p>
      </div>
    </section>
  </div>
</template>
