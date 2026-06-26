<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

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
  amount_10k: '金额(万元)',
  campaign_tag: '专项标签',
  cancel_date: '丢单/取消日期',
  cancel_reason: '丢单/取消原因',
  channel: '互动渠道',
  contact_count: '联系人数量',
  contact_name: '联系人姓名',
  content: '互动内容',
  customer_name: '客户名称',
  customer_stage: '客户阶段',
  department: '部门',
  email: '邮箱',
  event_time: '互动时间',
  expect_bid_date: '预计开标日期',
  expect_order_date: '预计下单日期',
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
  is_cancel_lost: '是否取消/丢单',
  is_existing_customer: '是否存量客户',
  is_funnel: '是否进入漏斗',
  is_high_value: '是否高价值行为',
  last_interaction_channel: '最近互动渠道',
  last_interaction_time: '最近互动时间',
  mobile: '手机号',
  mobile_count: '手机号数量',
  owner_name: '负责人',
  order_amount_10k: '订单金额(万元)',
  order_product_line: '订单产品线名称',
  opp_code: '业务机会编码',
  opp_name: '业务机会名称',
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
  win_rate: '赢率(%)',
  win_rate_1: '赢率2(%)',
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

function formatSourceFields(value) {
  const fields = splitList(value)
  return fields.length ? fields.map(formatSourceField).join(', ') : '-'
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
	      path: field.path || props.help.path || field.sourceField || field.variable || props.help.title,
	      sourceTable: field.sourceTable || field.sourceTables || props.help.sourceTables || '-',
	      sourceField: field.sourceFieldDisplay || (field.sourceField ? formatSourceFields(field.sourceField) : (field.sourceFields || props.help.sourceFields || '-')),
	      calculation: field.calculation || props.help.calculation || '-',
	      timeRule: field.timeRule || props.help.timeRule || '-',
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
	      path: props.help.path || props.help.title,
	      sourceTable: props.help.sourceTables || '-',
	      sourceField: '-',
	      calculation: props.help.calculation || '-',
	      timeRule: props.help.timeRule || '-',
	      emptyState: props.help.emptyState || '-',
	    }]
	  }

	  return sourceFields.map((field, index) => ({
	    type: fieldType(field),
	    variable: fieldName(field),
	    meaning: fieldComment(field),
	    path: props.help.path || field,
	    sourceTable: tableName(field, sourceTables, index),
	    sourceField: formatSourceField(field),
	    calculation: props.help.calculation || '-',
	    timeRule: props.help.timeRule || '-',
	    emptyState: props.help.emptyState || '-',
	  }))
	})

const triggerRef = ref(null)
const isOpen = ref(false)
const panelStyle = ref({})
let closeTimer = null

function clearCloseTimer() {
  if (closeTimer) {
    window.clearTimeout(closeTimer)
    closeTimer = null
  }
}

function positionPanel() {
  const trigger = triggerRef.value
  if (!trigger) return

  const rect = trigger.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const margin = 16
  const gap = 8
  const panelWidth = Math.min(500, viewportWidth - margin * 2)
  const estimatedPanelHeight = Math.min(620, viewportHeight - 96)

  let left = props.align === 'end'
    ? rect.right - panelWidth
    : rect.left
  left = Math.max(margin, Math.min(left, viewportWidth - panelWidth - margin))

  let top = rect.bottom + gap
  if (top + estimatedPanelHeight > viewportHeight - margin) {
    top = Math.max(margin, rect.top - estimatedPanelHeight - gap)
  }

  panelStyle.value = {
    top: `${top}px`,
    left: `${left}px`,
    width: `${panelWidth}px`,
    maxHeight: `${Math.min(620, viewportHeight - top - margin)}px`,
  }
}

async function openPanel() {
  clearCloseTimer()
  isOpen.value = true
  await nextTick()
  positionPanel()
  window.addEventListener('resize', positionPanel)
  window.addEventListener('scroll', positionPanel, true)
}

function scheduleClose() {
  clearCloseTimer()
  closeTimer = window.setTimeout(() => {
    if (document.activeElement === triggerRef.value) return
    isOpen.value = false
    window.removeEventListener('resize', positionPanel)
    window.removeEventListener('scroll', positionPanel, true)
  }, 120)
}

onBeforeUnmount(() => {
  clearCloseTimer()
  window.removeEventListener('resize', positionPanel)
  window.removeEventListener('scroll', positionPanel, true)
})
</script>

<template>
  <span
    class="field-help"
    :class="`field-help--${align}`"
    @mouseenter="openPanel"
    @mouseleave="scheduleClose"
  >
    <button
      ref="triggerRef"
      type="button"
      class="field-help__trigger"
      :aria-label="`查看${help.title}字段来源`"
      :aria-expanded="isOpen"
      @click.stop="openPanel"
      @focus="openPanel"
      @blur="scheduleClose"
    >
      ?
    </button>
    <Teleport to="body">
      <span
        v-if="isOpen"
        class="field-help__panel"
        :style="panelStyle"
        role="tooltip"
        @mouseenter="clearCloseTimer"
        @mouseleave="scheduleClose"
      >
        <span class="field-help__kicker">字段路径</span>
        <span class="field-help__title">
          {{ help.title }}
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
                <span>字段路径</span>
                <b>{{ field.path }}</b>
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
                <span>时间口径</span>
                <b>{{ field.timeRule }}</b>
              </span>
              <span class="field-help__row">
                <span>空值处理</span>
                <b>{{ field.emptyState }}</b>
              </span>
            </span>
          </span>
        </span>
      </span>
    </Teleport>
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

.field-help:hover,
.field-help:focus-within {
  z-index: 1000;
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
  position: fixed;
  z-index: 9999;
  max-height: min(620px, calc(100vh - 96px));
  overflow-y: auto;
  padding: 12px;
  border: 1px solid rgba(107, 141, 190, .42);
  border-radius: 9px;
  background: #07111f;
  box-shadow: 0 18px 44px rgba(0, 0, 0, .36), 0 0 0 1px rgba(90, 167, 255, .10);
  color: #eaf3ff;
  font-size: 11.5px;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
}

.field-help__kicker {
  display: block;
  margin-bottom: 6px;
  color: #5ff2d0;
  font-size: 10px;
  font-weight: 800;
}

.field-help__title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #f7fbff;
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
  border-top: 1px dashed rgba(107, 141, 190, .28);
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
  color: #f7fbff;
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
  grid-template-columns: 62px minmax(0, 1fr);
  gap: 10px;
  padding-top: 1px;
}

.field-help__row > span {
  color: #8ea2bf;
  font-weight: 700;
}

.field-help__row > b {
  color: #f7fbff;
  font-weight: 650;
}

:global(html[data-theme="light"] .field-help__panel) {
  border-color: var(--line);
  background: var(--panel2);
  box-shadow: 0 18px 48px rgba(21, 45, 83, .16), 0 0 0 1px rgba(255, 255, 255, .72);
  color: var(--text);
}

:global(html[data-theme="light"] .field-help__kicker),
:global(html[data-theme="light"] .field-help__title),
:global(html[data-theme="light"] .field-help__field-title) {
  color: var(--brand);
}

:global(html[data-theme="light"] .field-help__field-card) {
  border-top-color: rgba(166, 181, 205, .42);
}

:global(html[data-theme="light"] .field-help__row > span) {
  color: var(--muted);
}

:global(html[data-theme="light"] .field-help__row > b) {
  color: var(--text);
}

:global(html[data-theme="light"] .field-help__type--src) {
  color: #168f82;
}

:global(html[data-theme="light"] .field-help__type--calc) {
  color: #9b7108;
}

</style>
