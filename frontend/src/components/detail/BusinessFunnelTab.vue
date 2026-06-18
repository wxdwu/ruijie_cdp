<script setup>
import PrototypeChart from './PrototypeChart.vue'

const healthAxes = ['拜访活跃', '有效拜访', '漏斗厚度', '赢率', '成交体量']
const funnelRows = ['漏斗内 · 本客户', '漏斗内 · 同行均值', '漏斗外 · 本客户', '漏斗外 · 同行均值']
const stages = ['MQL', 'SQL', '方案', '投标', '谈判', '成交']
</script>

<template>
  <div class="prototype-tab">
    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2>经营健康度对位</h2><p>五维拉通本客户与同行业基准</p></div><span>Peer Radar</span></header>
        <div class="prototype-body"><PrototypeChart type="radar" :labels="healthAxes" :height="310" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2>漏斗金额 · 同行对位</h2><p>在/外漏斗金额对比同行均值</p></div><span>Funnel</span></header>
        <div class="prototype-body"><PrototypeChart type="bar" :labels="funnelRows" unit="万" :height="310" /></div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>商机阶段堆积</h2><p>各阶段金额（万）累计，越厚=漏斗越健康</p></div><span>Pipeline</span></header>
      <div class="prototype-body"><PrototypeChart type="stack" :labels="stages" unit="万" :height="245" /></div>
    </section>

    <section class="prototype-panel">
      <header><div><h2>AI 业务洞察</h2><p>基于本客户与同行字段的差距分析</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>漏斗内金额 <b>0万</b>，<span>暂无同行对比</span>。</p>
        <p>总拜访 <b>0</b> 次（有效 0），无拜访天数 0 天。</p>
        <p>商机赢率 <b>0%</b>，<span>暂无同行对比</span>。</p>
        <p>商机最聚集阶段：<b>暂无数据</b>。</p>
      </div>
    </section>
  </div>
</template>
