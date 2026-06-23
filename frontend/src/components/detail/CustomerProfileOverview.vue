<script setup>
const props = defineProps({
  customer: { type: Object, default: () => ({}) },
  customerStatistics: { type: Object, default: () => ({}) },
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

function formatAmount(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (number >= 10000) return `${(number / 10000).toFixed(1).replace(/\.0$/, '')} 万元`
  return `${number.toLocaleString()} 元`
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
  return normalizeList(props.customer.top_channels).map(channel => channelLabels[channel] || channel)
}
</script>

<template>
  <div class="profile-overview rounded-xl border border-[var(--line)] bg-[var(--panel)]">
    <div class="panel-heading">
      <div>
        <span class="text-sm font-semibold text-[var(--text)]">客户档案</span>
        <span class="ml-2 text-[10px] font-semibold tracking-widest text-[var(--muted)]">PROFILE</span>
      </div>
      <span class="text-xs text-[var(--muted)]">基础信息 · 业务标签 · 跟进状态 · 商机预算</span>
    </div>

    <div class="space-y-5 p-5">
      <section class="profile-block">
        <div class="mb-4 flex items-center justify-between">
          <div class="section-title">基础信息</div>
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
          <div class="profile-field">
            <span>采购阶段</span>
            <strong>{{ customer.purchase_stage || '—' }}</strong>
          </div>
          <div class="profile-field">
            <span>合作意向</span>
            <strong>{{ customer.intent_level || '—' }} · {{ customer.intent_score ?? 0 }} 分</strong>
          </div>
        </div>
      </section>

      <section>
        <div class="section-title mb-3">业务标签</div>
        <div class="flex flex-wrap gap-2">
          <span v-for="item in normalizeList(customer.product_categories)" :key="item" class="business-tag">
            {{ item }}
          </span>
          <span v-if="customer.industry" class="business-tag">{{ customer.industry }}</span>
          <span v-if="!normalizeList(customer.product_categories).length && !customer.industry" class="empty-text">
            暂无业务标签
          </span>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-6 border-t border-[var(--line)] pt-5 md:grid-cols-2">
        <section>
          <div class="section-title mb-3">跟进状态</div>
          <div class="compact-list">
            <div><span>最近互动</span><strong>{{ formatTime(customer.last_interaction_time) }}</strong></div>
            <div>
              <span>累计 / 计划 / 有效</span>
              <strong>{{ customerStatistics.interaction_count_total || 0 }} / 0 / {{ customerStatistics.interaction_count_total || 0 }}</strong>
            </div>
            <div>
              <span>偏好渠道</span>
              <strong>{{ preferredChannels().join('、') || '—' }}</strong>
            </div>
          </div>
        </section>

        <section>
          <div class="section-title mb-3">商机 &amp; 预算</div>
          <div class="compact-list">
            <div><span>漏斗商机</span><strong>{{ customer.funnel_opp_count || 0 }} 个</strong></div>
            <div><span>最高阶段</span><strong>{{ customer.forecast_type || '—' }}</strong></div>
            <div><span>当前商机</span><strong>{{ opportunities.length }} 个</strong></div>
            <div><span>近两年成交</span><strong>{{ formatAmount(customer.won_amount) }}</strong></div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-overview {
  overflow: hidden;
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
  padding: 4px 9px;
  background: rgba(79, 172, 254, 0.06);
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
