<script setup>
import { computed } from 'vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  customer: { type: Object, default: () => ({}) },
})

const help = {
  riskScore: {
    title: '风险评分',
    type: 'calc',
    fields: [
      {
        variable: '风险评分',
        meaning: '基于审批、公海、锁定、免打扰、部门风险、制裁风险、重复客户等字段加权识别。',
        sourceTable: '当前 DWS/已查 ODS 未发现',
        sourceField: 'approvalStatus, highSeaStatus, lockStatus, doNotDisturb, KHSP__c, KHSPWTG__c, departmentalRiskWarning__c, sanctionRiskWarning__c, duplicateFlg',
        calculation: '原型 CRM 客户主档字段当前未在已查表中发现；字段接入后按高/中/低风险点计数。',
        emptyState: '未接入时风险点显示 0，并提示待聚合。',
        type: 'calc',
      },
    ],
  },
  statusOverview: {
    title: '状态总览',
    type: 'src',
    fields: [
      {
        variable: '状态字段',
        meaning: '客户审批、公海、锁定、免打扰等客户主档状态。',
        sourceTable: '当前 DWS/已查 ODS 未发现',
        sourceField: 'approvalStatus, highSeaStatus, lockStatus, doNotDisturb, KHSP__c, KHSPWTG__c',
        calculation: '后续建议从 CRM 客户主档聚合到 dws_customer_360 或 dws_customer_risk。',
        emptyState: '未接入时显示 -。',
        type: 'src',
      },
    ],
  },
  riskActions: {
    title: '风险条目 · 处置建议',
    type: 'calc',
    fields: [
      {
        variable: '风险处置',
        meaning: '每条风险字段映射一个推荐动作。',
        sourceTable: '当前 DWS/已查 ODS 未发现，商机失败风险可参考 ods_crm_opportunity_day',
        sourceField: 'departmentalRiskWarning__c, sanctionRiskWarning__c, duplicateFlg, ods_crm_opportunity_day.is_cancel_lost, ods_crm_opportunity_day.cancel_reason',
        calculation: '合规风险字段接入后生成处置建议；商机取消/丢单只能作为失败风险补充，不等同合规风险。',
        emptyState: '无风险或字段未接入时显示当前未接入显著风险字段。',
        type: 'calc',
      },
    ],
  },
  approvalStatus: {
    title: '客户审批状态',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'approvalStatus',
    calculation: 'CRM 客户主档审批状态，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  highSeaStatus: {
    title: '公海状态',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'highSeaStatus',
    calculation: 'CRM 客户主档公海/认领状态，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  lockStatus: {
    title: '锁定状态',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'lockStatus',
    calculation: 'CRM 客户主档锁定状态，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  doNotDisturb: {
    title: '免打扰',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'doNotDisturb',
    calculation: 'CRM 客户主档触达限制字段，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  customerApproval: {
    title: '客户审批',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'KHSP__c',
    calculation: '原型客户审批字段，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  approvalRejectReason: {
    title: '审批未通过原因',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'KHSPWTG__c',
    calculation: '原型审批未通过原因字段，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  departmentalRisk: {
    title: '部门风险预警',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'departmentalRiskWarning__c',
    calculation: 'CRM 客户主档或风控字段，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  sanctionRisk: {
    title: '制裁风险预警',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'sanctionRiskWarning__c',
    calculation: 'CRM 客户主档或合规风控字段，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
  duplicateFlag: {
    title: '重复客户',
    type: 'src',
    sourceTables: '当前 DWS/已查 ODS 未发现',
    sourceFields: 'duplicateFlg',
    calculation: '客户主档重复标识，待后续聚合。',
    emptyState: '未接入时显示 -。',
  },
}

function pick(...keys) {
  for (const key of keys) {
    const value = props.customer?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return '-'
}

const statusRows = computed(() => [
  { label: '客户审批状态', value: pick('approvalStatus', 'approval_status'), help: help.approvalStatus },
  { label: '公海状态', value: pick('highSeaStatus', 'high_sea_status'), help: help.highSeaStatus },
  { label: '锁定状态', value: pick('lockStatus', 'lock_status'), help: help.lockStatus },
  { label: '免打扰', value: pick('doNotDisturb', 'do_not_disturb'), help: help.doNotDisturb },
  { label: '客户审批', value: pick('KHSP__c', 'customer_approval'), help: help.customerApproval },
  { label: '审批未通过原因', value: pick('KHSPWTG__c', 'approval_reject_reason'), help: help.approvalRejectReason },
  { label: '部门风险预警', value: pick('departmentalRiskWarning__c', 'departmental_risk_warning'), help: help.departmentalRisk },
  { label: '制裁风险预警', value: pick('sanctionRiskWarning__c', 'sanction_risk_warning'), help: help.sanctionRisk },
  { label: '重复客户', value: pick('duplicateFlg', 'duplicate_flag'), help: help.duplicateFlag },
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
        <header><div><h2 class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：风险评分输入">风险评分<FieldHelpTooltip :help="help.riskScore" /></h2><p>基于多个 CRM 风险字段加权识别</p></div><span>Risk Score</span></header>
        <div class="prototype-body risk-score-layout">
          <div><b :class="riskItems.length ? 'risk-bad' : 'risk-ok'">{{ riskItems.length }}</b><span>风险点数</span></div>
          <div><b class="risk-bad">{{ highRiskCount }}</b><span>高风险</span></div>
          <div><b>0</b><span>同行均值</span></div>
          <span class="prototype-badge">暂无对比</span>
          <p>越少越好。若 ≥ 同行均值，说明合规与触达条件需要清理。</p>
        </div>
      </section>

      <section class="prototype-panel">
        <header><div><h2>状态总览<FieldHelpTooltip :help="help.statusOverview" align="end" /></h2><p>审批 / 公海 / 锁定 / 免打扰</p></div><span>Status</span></header>
        <div class="prototype-body status-list">
          <div v-for="row in statusRows" :key="row.label">
            <span class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" :data-demo-missing="`缺原始字段：${row.label}`">{{ row.label }}<FieldHelpTooltip :help="row.help" /></span>
            <b>{{ row.value }}</b>
          </div>
        </div>
      </section>
    </div>

    <section class="prototype-panel">
      <header><div><h2>风险条目 · 处置建议<FieldHelpTooltip :help="help.riskActions" align="end" /></h2><p>每条风险对应一个推荐动作</p></div><span>Action</span></header>
      <div class="prototype-body">
        <div v-if="!riskItems.length" class="risk-clear-state">
          <span class="risk-check">✓</span>
          <div><b class="demo-missing-field demo-missing-field--compact demo-missing-field--inline" data-demo-missing="缺原始字段：部门/制裁/重复标识">当前未接入显著风险字段</b><p>审批、锁定、免打扰、部门风险、制裁风险、公海与重复客户字段目前未在 DWS/已查 ODS 中发现，后续聚合后自动生成处置建议。</p></div>
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
