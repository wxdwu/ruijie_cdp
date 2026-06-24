<script setup>
import PrototypeChart from './PrototypeChart.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
})

const budgetAxes = ['LAN', 'WAN', '数据中心', '云桌面', '智慧教室']
const outputRows = [
  '当年无线产出 · 本客户', '当年无线产出 · 同行均值',
  '当年路由产出 · 本客户', '当年路由产出 · 同行均值',
  '当年安全产出 · 本客户', '当年安全产出 · 同行均值',
]

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
  return `${numberValue(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}万`
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
        <header><div><h2>预算结构对位</h2><p>五大场景预算 vs 同行</p></div><span>Budget Mix</span></header>
        <div class="prototype-body"><PrototypeChart type="radar" :labels="budgetAxes" unit="万" :height="310" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2>预算兑现率</h2><p>近2年成交 / 预算总盘</p></div><span>Realize Rate</span></header>
        <div class="prototype-body">
          <div class="rate-display"><b>{{ realizeRate() }}%</b><span class="prototype-badge">暂无对比</span><span>同行均值 0%</span></div>
          <p class="prototype-note">预算总盘 {{ formatWan(totalBudget()) }} ｜ 已实现 {{ formatWan(realizedAmount()) }} ｜ 当年漏斗 {{ formatWan(pick('sumMoneyInFunnel__c', 'active_opp_amount')) }}</p>
          <div class="budget-kv">
            <div><span>产品线预算</span><b>{{ formatWan(pick('ProductBudget__c', 'product_budget')) }}</b></div>
            <div><span>历史成交</span><b>{{ formatWan(pick('historyWin__c', 'history_win')) }}</b></div>
            <div><span>LAN预算</span><b>{{ formatWan(pick('LANBudget__c', 'lan_budget')) }}</b></div>
            <div><span>WAN预算</span><b>{{ formatWan(pick('WANBudget__c', 'wan_budget')) }}</b></div>
            <div><span>数据中心预算</span><b>{{ formatWan(pick('DataCenterBudget__c', 'data_center_budget')) }}</b></div>
            <div><span>云桌面预算</span><b>{{ formatWan(pick('CloudDesktopBudget__c', 'cloud_desktop_budget')) }}</b></div>
            <div><span>智慧教室预算</span><b>{{ formatWan(pick('SmartClassroomBudget__c', 'smart_classroom_budget')) }}</b></div>
            <div><span>近2年成交</span><b>{{ formatWan(pick('totalWonOpportunityAmount', 'won_amount')) }}</b></div>
          </div>
        </div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>当年产出 · 找空间</h2><p>无线 / 路由 / 安全 当年产出 vs 同行均值</p></div><span>Output vs Peers</span></header>
      <div class="prototype-body"><PrototypeChart type="bar" :labels="outputRows" unit="万" :height="270" /></div>
    </section>

    <section class="prototype-panel">
      <header><div><h2>AI 预算洞察</h2><p>差距/重点/兑现率综合判定</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>当前暂无可识别的产出差距，等待无线、路由与安全产出字段接入。</p>
        <p>本客户产品线预算：<b>{{ formatWan(pick('ProductBudget__c', 'product_budget')) }}</b>。</p>
        <p>预算总盘 <b>{{ formatWan(totalBudget()) }}</b>，近2年成交 <b>{{ formatWan(realizedAmount()) }}</b>，兑现率 <b>{{ realizeRate() }}%</b>。</p>
        <p>漏斗内金额覆盖预算 <b>{{ totalBudget() ? Math.round(numberValue(pick('sumMoneyInFunnel__c', 'active_opp_amount')) / totalBudget() * 100) : 0 }}%</b>。</p>
      </div>
    </section>
  </div>
</template>
