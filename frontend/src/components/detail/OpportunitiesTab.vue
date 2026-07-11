<script setup>
import PrototypeChart from './PrototypeChart.vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  opportunities: { type: Array, default: () => [] },
})

const lossReasons = ['预算不足', '价格竞争', '竞品影响', '关键人缺失', '渠道问题', '流标 / 废标']
const stages = ['MQL', 'SQL', '方案', '投标', '谈判', '成交']
const help = {
  lossAnalysis: {
    title: '丢单维度归因',
    type: 'calc',
    fields: [
      {
        variable: '丢单维度',
        meaning: '将原始取消/丢单原因归并为预算、价格、竞品、关键人、渠道、流废标等业务维度。',
        sourceTable: 'ods_crm_opportunity_day',
        sourceField: 'ods_crm_opportunity_day.is_cancel_lost, ods_crm_opportunity_day.cancel_reason, ods_crm_opportunity_day.cancel_date, ods_crm_opportunity_day.amount_10k',
        calculation: 'cancel_reason 按关键词归类；金额暴露取丢单商机 amount_10k；同行均值当前未聚合。',
        emptyState: '无丢单原因时显示 0 或 —。',
        type: 'calc',
      },
    ],
  },
  stageDistribution: {
    title: '商机阶段分布',
    type: 'calc',
    fields: [
      {
        variable: '阶段分布',
        meaning: '统计客户商机在各阶段的条数或金额分布。',
        sourceTable: 'dws_customer_360, ods_crm_opportunity_day',
        sourceField: 'dws_customer_360.purchase_stage, dws_customer_360.forecast_type, dws_customer_360.highest_stage_opp, ods_crm_opportunity_day.customer_stage, ods_crm_opportunity_day.forecast_type',
        calculation: '优先使用 customer_stage，缺省回退 forecast_type；阶段分布目前从 ODS 明细实时归并或后续聚合进 DWS。',
        emptyState: '无商机时显示暂无数据。',
        type: 'calc',
      },
    ],
  },
  competitors: {
    title: '竞品对位',
    type: 'calc',
    fields: [
      {
        variable: '竞品',
        meaning: '主要竞品出现频次与同行业基准对比。',
        sourceTable: '当前 ods_crm_opportunity_day 未发现',
        sourceField: 'competitor, competitors',
        calculation: '原型字段当前未在 CRM 商机 ODS 中发现；需新增 CRM 字段或从商机备注/跟进记录抽取后聚合。',
        emptyState: '未接入时显示暂无竞品数据。',
        type: 'calc',
      },
    ],
  },
  opportunityInsight: {
    title: 'AI 商机洞察',
    type: 'calc',
    fields: [
      {
        variable: '商机洞察输入',
        meaning: '用于判断丢单维度、阶段聚集和竞品风险的字段集合。',
        sourceTable: 'ods_crm_opportunity_day, dws_customer_360',
        sourceField: 'ods_crm_opportunity_day.cancel_reason, ods_crm_opportunity_day.customer_stage, ods_crm_opportunity_day.forecast_type, ods_crm_opportunity_day.amount_10k, dws_customer_360.active_opp_count, dws_customer_360.active_opp_amount',
        calculation: '基于商机明细归因和阶段聚集生成说明；竞品/阻塞点缺失时标记暂无数据。',
        emptyState: '缺少字段时显示暂无数据或待聚合。',
        type: 'calc',
      },
    ],
  },
  opportunityDetail: {
    title: '商机明细',
    type: 'src',
    fields: [
      {
        variable: '商机明细',
        meaning: '当前客户名下 CRM 商机明细。',
        sourceTable: 'ods_crm_opportunity_day',
        sourceField: 'ods_crm_opportunity_day.opp_name, ods_crm_opportunity_day.opp_code, ods_crm_opportunity_day.customer_stage, ods_crm_opportunity_day.forecast_type, ods_crm_opportunity_day.amount_10k, ods_crm_opportunity_day.win_rate, ods_crm_opportunity_day.expect_order_date, ods_crm_opportunity_day.is_cancel_lost, ods_crm_opportunity_day.cancel_reason',
        calculation: '后端按 customer_name 查询 ODS 商机明细并按 create_date 倒序返回。',
        emptyState: '无商机时显示暂无商机数据。',
        type: 'src',
      },
    ],
  },
  oppName: {
    title: '商机',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.opp_name, ods_crm_opportunity_day.opp_code',
    calculation: '展示业务机会名称，缺省可回退业务机会编码。',
    emptyState: '无名称时显示 —。',
  },
  stage: {
    title: '阶段',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day, dws_customer_360',
    sourceFields: 'ods_crm_opportunity_day.customer_stage, ods_crm_opportunity_day.forecast_type, dws_customer_360.purchase_stage, dws_customer_360.forecast_type',
    calculation: '优先展示 customer_stage，缺省回退 forecast_type。',
    emptyState: '无阶段时显示 —。',
  },
  amount: {
    title: '金额',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day, dws_customer_360',
    sourceFields: 'ods_crm_opportunity_day.amount_10k, dws_customer_360.active_opp_amount',
    calculation: '明细展示 amount_10k；DWS active_opp_amount 用于客户级在途金额聚合。',
    emptyState: '无金额时显示 —。',
  },
  probability: {
    title: '概率',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.win_rate, ods_crm_opportunity_day.win_rate_1',
    calculation: '展示 CRM 商机赢率字段。',
    emptyState: '无赢率时显示 —。',
  },
  expectedClose: {
    title: '预计成交',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.expect_order_date, ods_crm_opportunity_day.expect_bid_date',
    calculation: '优先展示预计下单日期，缺省可参考预计开标日期。',
    emptyState: '无日期时显示 —。',
  },
  cancelLost: {
    title: '取消/丢单',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.is_cancel_lost',
    calculation: '直接展示是否取消/丢单标记。',
    emptyState: '无标记时显示 —。',
  },
  lossCategory: {
    title: '丢单维度',
    type: 'calc',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.cancel_reason',
    calculation: '按 cancel_reason 关键词归类为预算、价格、竞品、关键人、渠道、流废标或其他。',
    emptyState: '无原因时显示 —。',
  },
  rawReason: {
    title: '原始原因',
    type: 'src',
    sourceTables: 'ods_crm_opportunity_day',
    sourceFields: 'ods_crm_opportunity_day.cancel_reason',
    calculation: '直接展示 CRM 原始取消/丢单原因。',
    emptyState: '无原因时显示 —。',
  },
  blocker: {
    title: '阻塞点',
    type: 'calc',
    sourceTables: '当前 ods_crm_opportunity_day 未发现',
    sourceFields: 'blocker, blocking_point, stage_blocker, blocker_reason',
    calculation: '原型字段当前未在 CRM 商机 ODS 中发现；需后续新增字段或从跟进记录抽取。',
    emptyState: '未接入时显示 —。',
  },
  competitor: {
    title: '竞品',
    type: 'calc',
    sourceTables: '当前 ods_crm_opportunity_day 未发现',
    sourceFields: 'competitor, competitors',
    calculation: '原型字段当前未在 CRM 商机 ODS 中发现；需后续新增字段或从商机备注抽取。',
    emptyState: '未接入时显示 —。',
  },
}
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

function amountWan(item) {
  return pick(item, 'amount_10k', 'amount', 'opp_amount', 'opportunity_amount', 'amount_wan')
}

function lostReason(item) {
  return pick(item, 'cancel_reason', 'lost_reason', 'loss_reason')
}

function stageOf(item) {
  return pick(item, 'customer_stage', 'stage', 'forecast_type', 'sales_stage')
}

function lostFlag(item) {
  return pick(item, 'is_cancel_lost', 'cancel_or_lost', 'is_lost', 'lost_status')
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
  return props.opportunities.filter(item => categorizeLoss(lostReason(item)) === reason).length
}

function lostTotal() {
  return props.opportunities.filter(item => lostReason(item)).length
}

function topStage() {
  const counts = new Map()
  props.opportunities.forEach(item => {
    const stage = stageOf(item) || '暂无数据'
    counts.set(stage, (counts.get(stage) || 0) + 1)
  })
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || '暂无数据'
}
</script>

<template>
  <div class="prototype-tab">
    <section class="prototype-panel">
      <header><div><h2>丢单维度归因 · vs 同行业基准<FieldHelpTooltip :help="help.lossAnalysis" /></h2><p>将原始丢单原因归并到 6 个业务维度，对比本客户与同行业的差异结构</p></div><span>Loss Analysis</span></header>
      <div class="prototype-body">
        <div class="loss-summary">
          <div><b :class="lostTotal() ? 'risk-bad' : 'risk-ok'">{{ lostTotal() }}</b><span>本客户丢单</span></div>
          <div><b>{{ formatWan(opportunities.reduce((sum, item) => sum + (lostReason(item) ? Number(amountWan(item) || 0) : 0), 0)) }}</b><span>金额暴露</span></div>
          <div><b>{{ lossReasons.find(reason => lossCount(reason) > 0) || '无' }}</b><span>本客户 Top 丢单维度</span></div>
          <div class="demo-missing-field demo-missing-field--compact" data-demo-missing="需按同行客户聚合丢单基准"><b>无</b><span>同行 Top 丢单维度</span></div>
        </div>
        <div class="loss-table">
          <div class="loss-head"><span>丢单维度</span><span>本客户</span><span class="demo-missing-field demo-missing-field--compact" data-demo-missing="需按同行客户聚合">同行均值</span><span>金额暴露</span><span>标记</span></div>
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
        <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="需统一阶段并聚合同行基准">商机阶段分布<FieldHelpTooltip :help="help.stageDistribution" /></h2><p>阶段商机条数 vs 同行</p></div><span>Pipeline</span></header>
        <div class="prototype-body"><PrototypeChart type="stack" :labels="stages" :height="250" /></div>
      </section>
      <section class="prototype-panel">
        <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：竞品">竞品对位<FieldHelpTooltip :help="help.competitors" align="end" /></h2><p>主要竞品出现频次 vs 同行业基准</p></div><span>Competitors</span></header>
        <div class="prototype-body empty-chart-state"><b>0</b><span>暂无竞品数据</span></div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>AI 商机洞察<FieldHelpTooltip :help="help.opportunityInsight" align="end" /></h2><p>基于丢单维度/阶段/竞品综合判定</p></div><span>Insight</span></header>
      <div class="prototype-body prototype-insight-lines">
        <p>本客户丢单记录 <b>{{ lostTotal() }}</b> 条。同行业最常出现的丢单维度尚未聚合。</p>
        <p>商机最聚集于 <b>{{ topStage() }}</b> 阶段（{{ opportunities.length }} 个）。</p>
        <p><span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：竞品与阻塞点">主要竞品：<b>{{ opportunities.map(item => pick(item, 'competitor', 'competitors')).filter(Boolean)[0] || '暂无数据' }}</b></span>。</p>
      </div>
    </section>

    <section class="prototype-panel">
      <header><div><h2>商机明细<FieldHelpTooltip :help="help.opportunityDetail" align="end" /></h2><p>按阶段与金额排序，丢单原因已标注归因维度</p></div><span>Opportunities</span></header>
      <div class="table-scroll">
        <table class="prototype-table opportunity-table">
          <thead>
            <tr>
              <th>商机<FieldHelpTooltip :help="help.oppName" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="口径待统一">阶段<FieldHelpTooltip :help="help.stage" /></th>
              <th>金额<FieldHelpTooltip :help="help.amount" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="赢率口径待校准">概率<FieldHelpTooltip :help="help.probability" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="日期口径待统一">预计成交<FieldHelpTooltip :help="help.expectedClose" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="缺状态字段">取消/丢单<FieldHelpTooltip :help="help.cancelLost" /></th>
              <th>丢单维度<FieldHelpTooltip :help="help.lossCategory" align="end" /></th>
              <th>原始原因<FieldHelpTooltip :help="help.rawReason" align="end" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="缺原始字段">阻塞点<FieldHelpTooltip :help="help.blocker" align="end" /></th>
              <th class="demo-missing-field demo-missing-field--compact" data-demo-missing="缺原始字段">竞品<FieldHelpTooltip :help="help.competitor" align="end" /></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!opportunities.length"><td colspan="10"><div class="empty-state table-empty"><b>0</b><span>暂无商机数据</span></div></td></tr>
            <tr v-for="item in opportunities" v-else :key="pick(item, 'id', 'opp_id', 'opportunity_id', 'code')">
              <td class="opp-name"><b>{{ pick(item, 'opp_name', 'opportunity_name', 'name', 'business_opportunity_name', 'opp_code', 'opp_id', 'opportunity_id') || '—' }}</b></td>
              <td class="opp-stage">{{ stageOf(item) || '—' }}</td>
              <td class="opp-amount">{{ formatWan(amountWan(item)) }}</td>
              <td class="opp-number">{{ pick(item, 'probability', 'win_rate', 'winning_rate') || '—' }}</td>
              <td class="opp-date">{{ pick(item, 'expect_order_date', 'expected_close_date', 'close_date', 'expected_order_date') || '—' }}</td>
              <td class="opp-flag">{{ lostFlag(item) || '—' }}</td>
              <td>{{ categorizeLoss(lostReason(item)) }}</td>
              <td>{{ lostReason(item) || '—' }}</td>
              <td>{{ pick(item, 'blocker', 'blocking_point', 'stage_blocker') || '—' }}</td>
              <td>{{ pick(item, 'competitor', 'competitors') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
