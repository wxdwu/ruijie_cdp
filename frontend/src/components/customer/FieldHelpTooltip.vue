<script setup>
import { computed } from 'vue'

const props = defineProps({
  help: {
    type: Object,
    required: true,
  },
  align: {
    type: String,
    default: 'start',
  },
})

const FIELD_COMMENTS = {
  active_opp_amount: '在途商机金额',
  active_opp_count: '在途商机数',
  activity_level: '活跃度',
  amount: '商机金额',
  campaign_tag: '专项标签',
  channel: '互动渠道',
  contact_count: '联系人数量',
  contact_name: '联系人姓名',
  content: '互动内容',
  customer_name: '客户名称',
  customer_stage: '客户阶段',
  department: '部门',
  email: '邮箱',
  event_time: '互动时间',
  forecast_type: '预测类别',
  funnel_opp_count: '漏斗商机数',
  highest_stage_opp: '最高阶段商机',
  industry: '行业',
  intent_level: '意向等级',
  intent_score: '意向分',
  interaction_count: '历史互动次数',
  interaction_count_30d: '近30天互动次数',
  interaction_count_total: '总互动次数',
  is_active: '是否活跃商机',
  is_existing_customer: '是否存量客户',
  is_high_value: '是否高价值行为',
  last_interaction_channel: '最近互动渠道',
  last_interaction_time: '最近互动时间',
  mobile: '手机号',
  mobile_count: '手机号数量',
  owner_name: '负责人',
  position: '职位',
  product_categories: '产品分类',
  product_interests: '产品兴趣',
  purchase_role: '采购角色',
  purchase_stage: '采购阶段',
  region: '区域',
  role_category: '角色分类',
  role_coverage: '关键角色覆盖',
  source_table: '来源表标识',
  status: '状态',
  contact_validity: '联系人有效性',
  top_channels: 'Top互动渠道',
  top_content_types: '内容类型兴趣',
  won_amount: '成交金额',
}

function splitList(value) {
  if (Array.isArray(value)) return value
  if (!value) return []
  return String(value).split(',').map(item => item.trim()).filter(Boolean)
}

function fieldName(fieldPath) {
  return String(fieldPath).split('.').pop()
}

function tableName(fieldPath, fallbackTables, index) {
  const parts = String(fieldPath).split('.')
  if (parts.length > 1) return parts.slice(0, -1).join('.')
  return fallbackTables[index] || fallbackTables[0] || '-'
}

function fieldComment(fieldPath) {
  const name = fieldName(fieldPath)
  return FIELD_COMMENTS[name] || name
}

function formatSourceField(fieldPath) {
  const name = fieldName(fieldPath)
  return `${name}(${fieldComment(fieldPath)})`
}

function normalizeType(type) {
  return ['source', 'src'].includes(type) ? 'src' : 'calc'
}

function fieldType(fieldPath, explicitType) {
  if (explicitType) return normalizeType(explicitType)
  const fieldTypes = props.help.sourceFieldTypes || {}
  const name = fieldName(fieldPath)
  return normalizeType(fieldTypes[fieldPath] || fieldTypes[name] || props.help.type || 'src')
}

const fieldBlocks = computed(() => {
  if (Array.isArray(props.help.fields) && props.help.fields.length) {
    return props.help.fields.map(field => ({
      type: fieldType(field.sourceField || field.variable || props.help.title, field.type),
      variable: field.variable || fieldName(field.sourceField || props.help.title),
      meaning: field.meaning || fieldComment(field.sourceField || props.help.title),
      sourceTable: field.sourceTable || field.sourceTables || props.help.sourceTables || '-',
      sourceField: field.sourceFieldDisplay || (field.sourceField ? formatSourceField(field.sourceField) : (field.sourceFields || props.help.sourceFields || '-')),
      calculation: field.calculation || props.help.calculation || '-',
      emptyState: field.emptyState || props.help.emptyState || '-',
    }))
  }

  const sourceFields = splitList(props.help.sourceFields)
  const sourceTables = splitList(props.help.sourceTables)
  if (!sourceFields.length) {
    return [{
      type: fieldType(props.help.title),
      variable: props.help.title,
      meaning: props.help.meaning || props.help.title,
      sourceTable: props.help.sourceTables || '-',
      sourceField: '-',
      calculation: props.help.calculation || '-',
      emptyState: props.help.emptyState || '-',
    }]
  }

  return sourceFields.map((field, index) => ({
    type: fieldType(field),
    variable: fieldName(field),
    meaning: fieldComment(field),
    sourceTable: tableName(field, sourceTables, index),
    sourceField: formatSourceField(field),
    calculation: props.help.calculation || '-',
    emptyState: props.help.emptyState || '-',
  }))
})
</script>

<template>
  <span class="field-help" :class="`field-help--${align}`">
    <button
      type="button"
      class="field-help__trigger"
      :aria-label="`查看${help.title}字段来源`"
    >
      ?
    </button>
    <span class="field-help__panel" role="tooltip">
      <span class="field-help__title">
        {{ help.title }} · 字段来源
      </span>
      <span class="field-help__fields">
        <span
          v-for="(field, index) in fieldBlocks"
          :key="`${field.variable}-${index}`"
          class="field-help__field-card"
        >
          <span class="field-help__field-title">
            <span
              class="field-help__type"
              :class="field.type === 'src' ? 'field-help__type--src' : 'field-help__type--calc'"
            >
              {{ field.type === 'src' ? '源字段' : '计算' }}
            </span>
          </span>
          <span class="field-help__grid">
            <span class="field-help__row">
              <span>含义</span>
              <b>{{ field.meaning }}</b>
            </span>
            <span class="field-help__row">
              <span>来源表</span>
              <b>{{ field.sourceTable }}</b>
            </span>
            <span class="field-help__row">
              <span>来源字段</span>
              <b>{{ field.sourceField }}</b>
            </span>
            <span class="field-help__row">
              <span>计算逻辑</span>
              <b>{{ field.calculation }}</b>
            </span>
            <span class="field-help__row">
              <span>空值处理</span>
              <b>{{ field.emptyState }}</b>
            </span>
          </span>
        </span>
      </span>
    </span>
  </span>
</template>

<style scoped>
.field-help {
  position: relative;
  z-index: 30;
  display: inline-flex;
  margin-left: 6px;
  vertical-align: middle;
}

.field-help__trigger {
  display: inline-flex;
  width: 17px;
  height: 17px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(90, 167, 255, .48);
  border-radius: 999px;
  background: rgba(90, 167, 255, .12);
  color: var(--brand);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  transition: background-color .15s ease, border-color .15s ease, transform .15s ease;
}

.field-help__trigger:hover,
.field-help__trigger:focus-visible {
  border-color: rgba(90, 167, 255, .75);
  background: rgba(90, 167, 255, .22);
  outline: none;
  transform: scale(1.06);
}

.field-help__panel {
  position: absolute;
  top: 24px;
  left: 0;
  display: none;
  width: min(500px, calc(100vw - 48px));
  max-height: min(620px, calc(100vh - 96px));
  overflow-y: auto;
  padding: 12px;
  border: 1px solid rgba(90, 167, 255, .32);
  border-radius: 12px;
  background: linear-gradient(180deg, var(--panel2), var(--panel));
  box-shadow: var(--shadow), 0 0 0 1px rgba(90, 167, 255, .10);
  color: var(--text);
  font-size: 11.5px;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
}

.field-help--end .field-help__panel {
  right: 0;
  left: auto;
}

.field-help:hover .field-help__panel,
.field-help:focus-within .field-help__panel {
  display: block;
}

.field-help__kicker {
  display: block;
  margin-bottom: 6px;
  color: var(--brand);
  font-size: 10px;
  font-weight: 800;
}

.field-help__title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text);
  font-size: 12.5px;
  font-weight: 800;
}

.field-help__fields {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.field-help__field-card {
  display: block;
  border-top: 1px dashed var(--line);
  padding-top: 10px;
}

.field-help__field-card:first-child {
  border-top: 0;
  padding-top: 0;
}

.field-help__field-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text);
  font-size: 12.5px;
  font-weight: 800;
}

.field-help__type {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 800;
}

.field-help__type--src {
  border: 1px solid rgba(45, 212, 191, .32);
  background: rgba(45, 212, 191, .14);
  color: #2dd4bf;
}

.field-help__type--calc {
  border: 1px solid rgba(250, 204, 21, .30);
  background: rgba(250, 204, 21, .14);
  color: var(--warn);
}

.field-help__grid {
  display: grid;
  gap: 6px;
  margin-top: 7px;
}

.field-help__row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 10px;
  padding-top: 1px;
}

.field-help__row > span {
  color: var(--muted);
  font-weight: 700;
}

.field-help__row > b {
  color: var(--text);
  font-weight: 650;
}

:global(html[data-theme="light"]) .field-help__panel {
  border-color: rgba(90, 140, 210, .34);
  box-shadow: 0 18px 48px rgba(21, 45, 83, .16), 0 0 0 1px rgba(90, 167, 255, .08);
}

:global(html[data-theme="light"]) .field-help__type--src {
  color: #168f82;
}

:global(html[data-theme="light"]) .field-help__type--calc {
  color: #9b7108;
}

</style>
