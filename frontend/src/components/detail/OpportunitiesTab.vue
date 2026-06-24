<script setup>
import PrototypeChart from './PrototypeChart.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  opportunities: { type: Array, default: () => [] },
})

const lossReasons = ['预算不足', '价格竞争', '竞品影响', '关键人缺失', '渠道问题', '流标 / 废标']
const stages = ['MQL', 'SQL', '方案', '投标', '谈判', '成交']

function pick(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function formatWan(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return `¥${number.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}万`
}

function categorizeLoss(reason) {
  const text = String(reason || '')
  if (!text) return '—'
  if (/预算/.test(text)) return '预算不足'
  if (/价|报价|价格/.test(text)) return '价格竞争'
  if (/竞品|友商|竞争/.test(text)) return '竞品影响'
  if (/关键|联系人|决策/.test(text)) return '关键人缺失'
  if (/渠道|代理/.test(text)) return '渠道问题'
  if (/流标|废标|招标/.test(text)) return '流标 / 废标'
  return '其他'
}

function lossCount(reason) {
  return props.opportunities.filter(item => categorizeLoss(pick(item, 'lost_reason', 'loss_reason', 'cancel_reason')) === reason).length
}

function topStage() {
  const counts = new Map()
  props.opportunities.forEach(item => {
    const stage = pick(item, 'stage', 'forecast_type', 'sales_stage') || '暂无数据'
    counts.set(stage, (counts.get(stage) || 0) + 1)
  })
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || '暂无数据'
}
</script>

<template>
  <div class="prototype-tab">
    <section class="prototype-panel">
      <header><div><h2>丢单维度归因 · vs 同行业基准</h2><p>将原始丢单原因归并到 6 个业务维度，对比本客户与同行业的差异结构</p></div><span>Loss Analysis</span></header>
      <div class="prototype-body">
        <div class="loss-summary">
          <div><b :class="opportunities.length ? 'risk-bad' : 'risk-ok'">{{ opportunities.filter(item => pick(item, 'lost_reason', 'loss_reason', 'cancel_reason')).length }}</b><span>本客户丢单</span></div>
          <div><b>{{ formatWan(opportunities.reduce((sum, item) => sum + (pick(item, 'lost_reason', 'loss_reason', 'cancel_reason') ? Number(pick(item, 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan') || 0) : 0), 0)) }}</b><span>金额暴露</span></div>
          <div><b>{{ lossReasons.find(reason => lossCount(reason) > 0) || '无' }}</b><span>本客户 Top 丢单维度</span></div>
          <div><b>无</b><span>同行 Top 丢单维度</span></div>
        </div>
        <div class="loss-table">
          <div class="loss-head"><span>丢单维度</span><span>本客户</span><span>同行均值</span><span>金额暴露</span><span>标记</span></div>
          <div v-for="(reason, index) in lossReasons" :key="reason">
            <span class="loss-name"><i :class="`loss-dot tone-${index}`"></i>{{ reason }}</span>
            <span><i></i>{{ lossCount(reason) }}单</span>
            <span><i class="peer"></i>0单</span>
            <b>¥0</b>
            <em>—</em>
          </div>
        </div>
      </div>
    </section>

    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2>商机阶段分布</h2><p>阶段商机条数 vs 同行</p></div><span>Pipeline</span></header>
        <div class="prototype-body"><PrototypeChart type="stack" :labels="stages" :height="250" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2>竞品对位</h2><p>主要竞品出现频次 vs 同行业基准</p></div><span>Competitors</span></header>
        <div class="prototype-body empty-chart-state"><b>0</b><span>暂无竞品数据</span></div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>AI 商机洞察</h2><p>基于丢单维度/阶段/竞品综合判定</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>本客户丢单记录 <b>{{ opportunities.filter(item => pick(item, 'lost_reason', 'loss_reason', 'cancel_reason')).length }}</b> 条。同行业最常出现的丢单维度为 <b>无</b>。</p>
        <p>商机最聚集于 <b>{{ topStage() }}</b> 阶段（{{ opportunities.length }} 个）。</p>
        <p>主要竞品：<b>{{ opportunities.map(item => pick(item, 'competitor', 'competitors')).filter(Boolean)[0] || '暂无数据' }}</b>。</p>
      </div>
    </section>

    <section class="prototype-panel">
      <header><div><h2>商机明细</h2><p>按阶段与金额排序，丢单原因已标注归因维度</p></div><span>Opportunities</span></header>
      <div class="table-scroll">
        <table class="prototype-table opportunity-table">
          <thead>
            <tr>
              <th>商机</th><th>阶段</th><th>金额</th><th>概率</th><th>预计成交</th>
              <th>取消/丢单</th><th>丢单维度</th><th>原始原因</th><th>阻塞点</th><th>竞品</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!opportunities.length"><td colspan="10"><div class="empty-state table-empty"><b>0</b><span>暂无商机数据</span></div></td></tr>
            <tr v-for="item in opportunities" v-else :key="pick(item, 'id', 'opp_id', 'opportunity_id', 'code')">
              <td><b>{{ pick(item, 'opp_name', 'opportunity_name', 'name', 'business_opportunity_name', 'opp_id', 'opportunity_id') || '—' }}</b></td>
              <td>{{ pick(item, 'stage', 'forecast_type', 'sales_stage') || '—' }}</td>
              <td>{{ formatWan(pick(item, 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan')) }}</td>
              <td>{{ pick(item, 'probability', 'win_rate', 'winning_rate') || '—' }}</td>
              <td>{{ pick(item, 'expected_close_date', 'close_date', 'expected_order_date') || '—' }}</td>
              <td>{{ pick(item, 'cancel_or_lost', 'is_lost', 'lost_status') || '—' }}</td>
              <td>{{ categorizeLoss(pick(item, 'lost_reason', 'loss_reason', 'cancel_reason')) }}</td>
              <td>{{ pick(item, 'lost_reason', 'loss_reason', 'cancel_reason') || '—' }}</td>
              <td>{{ pick(item, 'blocker', 'blocking_point', 'stage_blocker') || '—' }}</td>
              <td>{{ pick(item, 'competitor', 'competitors') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
