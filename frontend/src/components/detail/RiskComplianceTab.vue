<script setup>
const statusRows = [
  ['客户审批状态', '-'],
  ['公海状态', '-'],
  ['锁定状态', '-'],
  ['免打扰', '-'],
  ['客户审批', '-'],
  ['审批未通过原因', '-'],
]
</script>

<template>
  <div class="prototype-tab">
    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2>风险评分</h2><p>基于多个 CRM 风险字段加权识别</p></div><span>Risk Score</span></header>
        <div class="prototype-body risk-score-layout">
          <div><b class="risk-ok">0</b><span>风险点数</span></div>
          <div><b class="risk-bad">0</b><span>高风险</span></div>
          <div><b>0</b><span>同行均值</span></div>
          <span class="prototype-badge">暂无对比</span>
          <p>越少越好。若 ≥ 同行均值，说明合规与触达条件需要清理。</p>
        </div>
      </section>

      <section class="prototype-panel">
        <header><div><h2>状态总览</h2><p>审批 / 公海 / 锁定 / 免打扰</p></div><span>Status</span></header>
        <div class="prototype-body status-list">
          <div v-for="row in statusRows" :key="row[0]"><span>{{ row[0] }}</span><b>{{ row[1] }}</b></div>
        </div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>风险条目 · 处置建议</h2><p>每条风险对应一个推荐动作</p></div><span>Action</span></header>
      <div class="prototype-body">
        <div class="risk-clear-state">
          <span class="risk-check">✓</span>
          <div><b>当前未识别到显著风险</b><p>接入审批、锁定、免打扰、部门风险、制裁风险、公海与重复客户字段后自动生成处置建议。</p></div>
        </div>
      </div>
    </section>
  </div>
</template>
