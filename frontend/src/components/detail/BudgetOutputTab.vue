<script setup>
import PrototypeChart from './PrototypeChart.vue'

const budgetAxes = ['LAN', 'WAN', '数据中心', '云桌面', '智慧教室']
const outputRows = [
  '当年无线产出 · 本客户', '当年无线产出 · 同行均值',
  '当年路由产出 · 本客户', '当年路由产出 · 同行均值',
  '当年安全产出 · 本客户', '当年安全产出 · 同行均值',
]
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
          <div class="rate-display"><b>0%</b><span class="prototype-badge">暂无对比</span><span>同行均值 0%</span></div>
          <p class="prototype-note">预算总盘 0万 ｜ 已实现 0万 ｜ 当年漏斗 0万</p>
          <div class="budget-kv">
            <div><span>产品线预算</span><b>0万</b></div>
            <div><span>历史成交</span><b>0万</b></div>
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
        <p>本客户最大单项预算：<b>暂无数据</b>。</p>
        <p>预算总盘 <b>0万</b>，近2年成交 <b>0万</b>，兑现率 <b>0%</b>。</p>
        <p>漏斗内金额覆盖预算 <b>0%</b>。</p>
      </div>
    </section>
  </div>
</template>
