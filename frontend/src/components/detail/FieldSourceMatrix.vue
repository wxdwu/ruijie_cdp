<script setup>
defineProps({
  title: { type: String, default: '字段口径' },
  rows: { type: Array, default: () => [] },
})
</script>

<template>
  <section class="prototype-panel source-matrix-panel">
    <header>
      <div>
        <h2>{{ title }}</h2>
        <p>参考原型问号提示，按当前库表拆解可用字段、ODS 待聚合字段和缺口</p>
      </div>
      <span>Field Map</span>
    </header>
    <div class="source-matrix">
      <div class="source-matrix-head">
        <span>模块/指标</span>
        <span>DWS 可用字段</span>
        <span>ODS 待聚合字段</span>
        <span>缺字段/标记</span>
        <span>口径</span>
      </div>
      <div v-for="row in rows" :key="row.metric" class="source-matrix-row">
        <b>{{ row.metric }}</b>
        <span>{{ row.dws || '—' }}</span>
        <span>{{ row.ods || '—' }}</span>
        <span :class="row.missing ? 'source-missing' : 'source-ok'">{{ row.missing || '已覆盖' }}</span>
        <p>{{ row.rule }}</p>
      </div>
    </div>
  </section>
</template>
