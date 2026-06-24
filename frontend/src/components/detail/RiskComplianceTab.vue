<script setup>
import { computed } from 'vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
})

function pick(...keys) {
  for (const key of keys) {
    const value = props.customer?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return '-'
}

const statusRows = computed(() => [
  ['客户审批状态', pick('approvalStatus', 'approval_status')],
  ['公海状态', pick('highSeaStatus', 'high_sea_status')],
  ['锁定状态', pick('lockStatus', 'lock_status')],
  ['免打扰', pick('doNotDisturb', 'do_not_disturb')],
  ['客户审批', pick('KHSP__c', 'customer_approval')],
  ['审批未通过原因', pick('KHSPWTG__c', 'approval_reject_reason')],
  ['部门风险预警', pick('departmentalRiskWarning__c', 'departmental_risk_warning')],
  ['制裁风险预警', pick('sanctionRiskWarning__c', 'sanction_risk_warning')],
  ['重复客户', pick('duplicateFlg', 'duplicate_flag')],
])

const riskItems = computed(() => {
  const items = []
  const push = (level, title, detail, action) => items.push({ level, title, detail, action })
  if (pick('approvalStatus', 'approval_status') !== '-') push('中', '审批状态需关注', pick('approvalStatus', 'approval_status'), '推动审批补齐资料')
  if (String(pick('lockStatus', 'lock_status')).includes('锁')) push('高', '客户已锁定', pick('lockStatus', 'lock_status'), '联系运营解锁或转交锁定方')
  if (['是', 'true', '1'].includes(String(pick('doNotDisturb', 'do_not_disturb')))) push('高', '客户免打扰', 'DoNotDisturb=是', '暂停外呼/邮件触达，转线下')
  if (pick('departmentalRiskWarning__c', 'departmental_risk_warning') !== '-') push('高', '部门风险预警', pick('departmentalRiskWarning__c', 'departmental_risk_warning'), '上报合规并联合方案部门会诊')
  if (pick('sanctionRiskWarning__c', 'sanction_risk_warning') !== '-') push('中', '制裁/出口风险', pick('sanctionRiskWarning__c', 'sanction_risk_warning'), '走法务/合规预审，禁用受限品类')
  if (pick('duplicateFlg', 'duplicate_flag') !== '-') push('低', '客户重复登记', pick('duplicateFlg', 'duplicate_flag'), '在 CRM 合并主档')
  return items
})

const highRiskCount = computed(() => riskItems.value.filter(item => item.level === '高').length)
</script>

<template>
  <div class="prototype-tab">
    <div class="prototype-grid-2">
      <section class="prototype-panel">
        <header><div><h2>风险评分</h2><p>基于多个 CRM 风险字段加权识别</p></div><span>Risk Score</span></header>
        <div class="prototype-body risk-score-layout">
          <div><b :class="riskItems.length ? 'risk-bad' : 'risk-ok'">{{ riskItems.length }}</b><span>风险点数</span></div>
          <div><b class="risk-bad">{{ highRiskCount }}</b><span>高风险</span></div>
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
        <div v-if="!riskItems.length" class="risk-clear-state">
          <span class="risk-check">✓</span>
          <div><b>当前未识别到显著风险</b><p>接入审批、锁定、免打扰、部门风险、制裁风险、公海与重复客户字段后自动生成处置建议。</p></div>
        </div>
        <div v-else class="space-y-3">
          <div v-for="item in riskItems" :key="`${item.title}-${item.detail}`" class="rounded-lg border border-[var(--line)] bg-white/5 p-4">
            <div class="mb-2 flex items-center gap-2">
              <span class="prototype-badge">{{ item.level }}</span>
              <b class="text-sm text-[var(--text)]">{{ item.title }}</b>
            </div>
            <p class="text-xs leading-6 text-[var(--muted)]">{{ item.detail }}</p>
            <p class="mt-2 text-xs leading-6 text-[var(--brand)]">建议动作：{{ item.action }}</p>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
