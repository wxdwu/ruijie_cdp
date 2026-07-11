<script setup>
import { ref, computed } from 'vue'
import AiPriorityContact from './AiPriorityContact.vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  contacts: { type: Array, default: () => [] },
  recommendation: { type: Object, default: null },
  // AI 推荐联系人列表（从 ai-insight API 获取）
  recommendations: { type: Array, default: () => [] },
  // 推荐来源标记
  recommendSource: { type: String, default: "rule" },
})

const searchQuery = ref('')
const selectedRole = ref('')
const selectedStage = ref('')
const selectedInteractionMin = ref('')
const selectedHistoryType = ref('')
const vipOnly = ref(false)
const selectedContactKey = ref('')

const EMPTY_VALUES = new Set(['', '-', 'none', 'null', 'undefined', '未知', '无', '[]', '{}'])

const activityLabels = {
  high: '高',
  medium: '中',
  low: '低',
  none: '无互动',
  高: '高',
  中: '中',
  低: '低',
}

const sourceLabels = {
  crm: 'CRM',
  marketing: 'Marketing',
  zhique: '致趣',
  linkflow: 'Linkflow',
  tianrun: '天润',
}

const stages = computed(() => {
  return [...new Set(props.contacts.map(c => textValue(c.purchase_stage || c.purchaseStage)).filter(value => value !== '-'))]
})

const roles = computed(() => {
  return [...new Set(props.contacts.map(c => roleLabel(c)).filter(value => value !== '-'))]
})

const filteredContacts = computed(() => {
  let result = props.contacts

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(c =>
      String(c.contact_name || '').toLowerCase().includes(query) ||
      String(c.mobile || '').includes(searchQuery.value) ||
      String(c.position || '').toLowerCase().includes(query) ||
      String(c.department || '').toLowerCase().includes(query)
    )
  }

  if (selectedRole.value) {
    result = result.filter(c => roleLabel(c) === selectedRole.value)
  }

  if (selectedStage.value) {
    result = result.filter(c => textValue(c.purchase_stage || c.purchaseStage) === selectedStage.value)
  }

  if (selectedInteractionMin.value) {
    const min = Number(selectedInteractionMin.value)
    result = result.filter(c => Number(c.interaction_count || c.interaction_count_30d || 0) >= min)
  }

  if (selectedHistoryType.value === 'recent') {
    result = result.filter(c => c.last_interaction_time)
  } else if (selectedHistoryType.value === 'high') {
    result = result.filter(c => Number(c.high_value_count || 0) > 0)
  } else if (selectedHistoryType.value === 'any') {
    result = result.filter(c => Number(c.interaction_count || 0) > 0)
  }

  if (vipOnly.value) {
    result = result.filter(c => ['拍板者', '决策者'].includes(roleLabel(c)))
  }

  return result
})

const selectedContact = computed(() => {
  return filteredContacts.value.find(contact => contactKey(contact) === selectedContactKey.value)
    || filteredContacts.value[0]
    || null
})

function contactKey(contact) {
  return String(contact?.id || contact?.contact_id || contact?.linkflow_contact_id || contact?.mobile || contact?.email || contact?.contact_name || '')
}

function selectContact(contact) {
  selectedContactKey.value = contactKey(contact)
}

function isMeaningful(value) {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.some(isMeaningful)
  if (typeof value === 'object') return Object.values(value).some(isMeaningful)
  return !EMPTY_VALUES.has(String(value).trim())
}

function parseJsonValue(value) {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text || (!text.startsWith('[') && !text.startsWith('{'))) return value
  try {
    return JSON.parse(text)
  } catch {
    return value
  }
}

function formatListValue(value) {
  const parsed = parseJsonValue(value)
  if (Array.isArray(parsed)) {
    const values = parsed.map(item => textValue(item)).filter(item => item !== '-')
    return values.length ? [...new Set(values)].join('、') : '-'
  }
  if (parsed && typeof parsed === 'object') {
    const values = Object.values(parsed).map(item => textValue(item)).filter(item => item !== '-')
    return values.length ? [...new Set(values)].join('、') : '-'
  }
  if (!isMeaningful(parsed)) return '-'
  return String(parsed).replace(/\|/g, '、')
}

function textValue(value) {
  if (!isMeaningful(value)) return '-'
  return formatListValue(value)
}

function display(contact, ...keys) {
  for (const key of keys) {
    const value = contact?.[key]
    if (isMeaningful(value)) return textValue(value)
  }
  return '-'
}

function formatTime(val) {
  if (!val) return '-'
  const date = new Date(val)
  if (Number.isNaN(date.getTime())) return val
  return date.toLocaleString('zh-CN', { hour12: false })
}

function score(contact) {
  return display(recommendationFor(contact), 'relevance_score', 'priority_score', 'ai_relevance_score')
}

function roleLabel(contact) {
  return display(contact, 'role_category', 'purchase_role', 'roleTag')
}

function activityLabel(contact) {
  const value = contact?.activity_level
  if (value === null || value === undefined || value === '') return '-'
  const raw = String(value).trim()
  if (activityLabels[raw]) return activityLabels[raw]
  return isMeaningful(raw) ? raw : '-'
}

function contactStatus(contact) {
  const activity = activityLabel(contact)
  if (activity === '-') return '-'
  return activity === '无互动' ? '暂无互动' : `${activity}活跃`
}

function sourceText(contact) {
  const raw = parseJsonValue(contact?.source_tables ?? contact?.source_table ?? contact?.dataSource)
  const values = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object'
      ? Object.values(raw)
      : [raw]
  const labels = values
    .map(value => String(value || '').trim())
    .filter(isMeaningful)
    .map(value => sourceLabels[value] || value)
  return labels.length ? [...new Set(labels)].join('、') : '-'
}

function subtitle(contact) {
  const parts = [display(contact, 'position'), display(contact, 'department')]
    .filter(value => value !== '-')
  return parts.length ? parts.join(' · ') : '-'
}

function recommendationFor(contact) {
  if (!contact) return null
  const candidates = props.recommendations?.length
    ? props.recommendations
    : (props.recommendation ? [props.recommendation] : [])
  return candidates.find(item =>
    (item.contact_name && item.contact_name === contact.contact_name) ||
    (item.mobile && item.mobile === contact.mobile) ||
    (item.email && item.email === contact.email)
  ) || null
}

function recommendDisplay(contact, ...keys) {
  return display(recommendationFor(contact), ...keys)
}

const help = {
  contactList: {
    title: '联系人列表',
    type: 'calc',
    meaning: '当前客户下归并后的联系人清单，可按角色、采购阶段、互动次数和历史行为筛选。',
    sourceTables: 'dws_contact_360, dws_contact_mapping, dws_interaction_detail',
    sourceFields: 'dws_contact_360.contact_name, dws_contact_360.mobile, dws_contact_360.email, dws_contact_360.department, dws_contact_360.position, dws_contact_360.role_category, dws_contact_360.interaction_count, dws_contact_360.last_interaction_time',
    calculation: '联系人优先从 dws_contact_360 读取；空时回退 dws_contact_mapping。联系人按手机号、邮箱、contact_id 或姓名归并，互动次数取关联行为记录汇总。',
    emptyState: '无匹配联系人时显示暂无匹配的联系人。',
  },
  contactDetail: {
    title: '联系人详细情况',
    type: 'src',
    meaning: '选中联系人的主档、角色、兴趣、触达偏好和推进建议。',
    sourceTables: 'dws_contact_360, dws_contact_mapping',
    sourceFields: 'dws_contact_360.contact_name, dws_contact_360.position, dws_contact_360.department, dws_contact_360.mobile, dws_contact_360.email, dws_contact_360.purchase_role, dws_contact_360.role_category, dws_contact_360.activity_level, dws_contact_360.intent_level, dws_contact_mapping.source_table',
    calculation: '点击左侧联系人后展示该联系人全部可用字段；缺失字段保留占位，等待后端补齐。',
    emptyState: '字段缺失时显示 -。',
  },
  phone: {
    title: '手机号 / 办公电话',
    type: 'src',
    meaning: '联系人手机和办公电话。',
    sourceTables: 'dws_contact_360',
    sourceFields: 'dws_contact_360.mobile',
    calculation: '手机号来自 dws_contact_360.mobile；办公电话当前 DWS 未落字段，缺失时显示 -。',
    emptyState: '无号码时显示 -。',
  },
  email: {
    title: '邮箱',
    type: 'src',
    meaning: '联系人邮箱地址。',
    sourceTables: 'dws_contact_360',
    sourceFields: 'dws_contact_360.email',
    calculation: '邮箱来自 dws_contact_360.email。',
    emptyState: '无邮箱时显示 -。',
  },
  relation: {
    title: '关系',
    type: 'src',
    meaning: '联系人之间的汇报或业务关系。',
    sourceTables: '-',
    sourceFields: '-',
    calculation: '当前 DWS 未落联系人关系字段，页面保留 -。',
    emptyState: '无关系数据时显示 -。',
  },
  purchaseStage: {
    title: '采购阶段',
    type: 'calc',
    meaning: '联系人关联的采购阶段或线索跟进阶段。',
    sourceTables: 'dws_contact_360, dws_customer_360',
    sourceFields: 'dws_contact_360.lead_stage, dws_customer_360.purchase_stage',
    calculation: '优先展示联系人级 lead_stage；为空时回退客户级 dws_customer_360.purchase_stage。',
    emptyState: '无法判断时显示 -。',
  },
  status: {
    title: '联系人状态',
    type: 'src',
    meaning: '联系人有效性、线索状态或 CRM 联系人状态。',
    sourceTables: 'dws_contact_360',
    sourceFields: 'dws_contact_360.activity_level',
    calculation: '当前 DWS 未落稳定联系人状态字段；页面暂按 activity_level 派生活跃/暂无互动状态。',
    emptyState: '无状态时显示 -。',
  },
  activityIntent: {
    title: '活跃度 / 合作意向',
    type: 'calc',
    fields: [
      {
        type: 'calc',
        variable: 'activity_level',
        meaning: '当前联系人的互动活跃度。',
        sourceTable: 'dws_contact_360',
        sourceFieldDisplay: 'activity_level(联系人活跃度)',
        calculation: '按联系人互动次数分级：近30天互动不少于10次为高，不少于3次为中；近30天不足3次但存在历史互动为低；没有互动为无互动。',
        timeRule: '近30天以 ETL 执行时间为基准动态统计。',
        emptyState: '没有联系人活跃度时显示 -。',
      },
      {
        type: 'calc',
        variable: 'display_intent_level',
        meaning: '合作意向优先取联系人级意向；联系人级意向为空时回退为所属客户的合作意向。',
        sourceTable: 'dws_contact_360, dws_customer_360',
        sourceFieldDisplay: 'dws_contact_360.intent_level / dws_customer_360.intent_level',
        calculation: '接口使用 COALESCE(dws_contact_360.intent_level, dws_customer_360.intent_level)。客户级意向规则为：近30天互动不少于10次且有在途商机为高；不少于3次为中；只有历史互动为低；无互动为无。',
        timeRule: '客户近30天互动以当前时间向前30天统计。',
        emptyState: '联系人级和客户级意向均缺失时显示 -。',
      },
    ],
  },
  contentInterest: {
    title: '内容类型兴趣',
    type: 'src',
    meaning: '联系人互动过的内容主题或内容类型兴趣。',
    sourceTables: 'dws_contact_360, dws_interaction_detail',
    sourceFields: 'dws_contact_360.top_content_types, dws_interaction_detail.content, dws_interaction_detail.behavior_type',
    calculation: '内容兴趣优先展示 dws_contact_360.top_content_types；该字段由互动明细 content 和 behavior_type 聚合而来。',
    emptyState: '无内容兴趣时显示 -。',
  },
  productInterest: {
    title: '产品兴趣',
    type: 'src',
    meaning: '联系人表现出的产品兴趣。',
    sourceTables: 'dws_contact_360, dws_interaction_detail',
    sourceFields: 'dws_contact_360.product_interests, dws_interaction_detail.content',
    calculation: '产品兴趣优先展示 dws_contact_360.product_interests；该字段由互动内容或产品关键词聚合而来。',
    emptyState: '无产品兴趣时显示 -。',
  },
  preferredChannel: {
    title: '偏好触达',
    type: 'calc',
    meaning: '联系人更适合的触达渠道。',
    sourceTables: 'dws_interaction_detail, dws_contact_360',
    sourceFields: 'dws_interaction_detail.channel, dws_interaction_detail.event_time, dws_contact_360.last_interaction_time',
    calculation: '后端按 dws_interaction_detail.channel 对当前联系人分组计数，取互动次数最高且最近的渠道。',
    emptyState: '无互动渠道时显示 -。',
  },
  playbook: {
    title: '推进方式 / 推进话术',
    type: 'calc',
    meaning: '面向该联系人的建议触达方式和销售话术。',
    sourceTables: 'dws_contact_360, dws_customer_360, dws_interaction_detail',
    sourceFields: 'dws_contact_360.role_category, dws_contact_360.interaction_count_30d, dws_contact_360.mobile, dws_contact_360.email, dws_customer_360.purchase_stage, dws_interaction_detail.is_high_value',
    calculation: '推进方式和推荐话术来自 ai-insight 推荐结果；详情区按当前选中联系人姓名、手机号或邮箱匹配 recommendations。',
    emptyState: '暂无推荐时显示 -。',
  },
  behavior: {
    title: '该人的互动行为',
    type: 'calc',
    meaning: '选中联系人关联的历史互动、近30天互动、高价值行为和最近互动时间。',
    sourceTables: 'dws_contact_360, dws_interaction_detail',
    sourceFields: 'dws_contact_360.interaction_count, dws_contact_360.interaction_count_30d, dws_contact_360.last_interaction_time, dws_interaction_detail.is_high_value',
    calculation: '历史互动、近30天互动和最近互动时间来自 dws_contact_360；高价值行为可由 dws_interaction_detail.is_high_value 按联系人实时统计或后续写入聚合表。',
    emptyState: '无互动时显示 0 或 -。',
  },
}
</script>

<template>
  <div class="space-y-6">
    <!-- AI Priority Contact Banner -->
    <AiPriorityContact
      :recommendation="recommendation"
      :recommendations="recommendations"
      :source="recommendSource"
    />

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="flex-1">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索联系人姓名..."
          class="w-full rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--brand)]"
        />
      </div>
      <select
        v-model="selectedStage"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
      >
        <option value="">采购阶段：全部</option>
        <option v-for="stage in stages" :key="stage" :value="stage">{{ stage }}</option>
      </select>
      <select
        v-model="selectedRole"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
      >
        <option value="">角色：全部</option>
        <option v-for="role in roles" :key="role" :value="role">角色：{{ role }}</option>
      </select>
      <select
        v-model="selectedInteractionMin"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
      >
        <option value="">互动次数：全部</option>
        <option value="3">互动次数：3+</option>
        <option value="6">互动次数：6+</option>
        <option value="10">互动次数：10+</option>
      </select>
      <select
        v-model="selectedHistoryType"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
      >
        <option value="">历史行为：全部</option>
        <option value="recent">近14天有互动</option>
        <option value="high">有高价值互动</option>
        <option value="any">有历史行为</option>
      </select>
      <label class="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--muted)]">
        <input v-model="vipOnly" type="checkbox" />
        仅关键
      </label>
      <span class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-2 text-sm text-[var(--muted)]">
        筛选后 {{ filteredContacts.length }}/{{ contacts.length }}
      </span>
    </div>

    <div v-if="filteredContacts.length" class="contacts-layout">
      <section class="contacts-list-panel">
        <div class="contacts-list-header">
          <span>联系人列表<FieldHelpTooltip :help="help.contactList" /></span>
          <b>{{ filteredContacts.length }}</b>
        </div>
        <button
          v-for="(contact, index) in filteredContacts"
          :key="contactKey(contact) || index"
          type="button"
          class="contact-list-row"
          :class="{ active: contactKey(contact) === contactKey(selectedContact) }"
          @click="selectContact(contact)"
        >
          <span class="contact-rank">{{ index + 1 }}</span>
          <span class="contact-row-main">
            <span class="contact-row-title">
              <b>{{ contact.contact_name || '未命名联系人' }}</b>
              <em v-if="roleLabel(contact) !== '-'">{{ roleLabel(contact) }}</em>
            </span>
            <span class="contact-row-sub">
              {{ subtitle(contact) }}
            </span>
            <span class="contact-row-meta">
              手机 {{ display(contact, 'mobile') }} · 互动 {{ contact.interaction_count || 0 }} 次 · 最近 {{ formatTime(contact.last_interaction_time) }}
            </span>
          </span>
          <span class="contact-row-score">
            <b>{{ score(contact) }}</b>
            <small>相关性</small>
          </span>
        </button>
      </section>

      <aside class="contact-detail-panel" v-if="selectedContact">
        <div class="contact-detail-header">
          <div>
            <h3>{{ selectedContact.contact_name || '未命名联系人' }}<FieldHelpTooltip :help="help.contactDetail" /></h3>
            <p>{{ subtitle(selectedContact) }}</p>
          </div>
          <div class="contact-detail-badges">
            <span v-if="roleLabel(selectedContact) !== '-'">{{ roleLabel(selectedContact) }}</span>
            <span v-if="activityLabel(selectedContact) !== '-'">{{ activityLabel(selectedContact) }}</span>
          </div>
        </div>

        <div class="contact-detail-grid">
          <div><span>手机<FieldHelpTooltip :help="help.phone" /></span><strong>{{ display(selectedContact, 'mobile') }}</strong></div>
          <div><span>邮箱<FieldHelpTooltip :help="help.email" /></span><strong>{{ display(selectedContact, 'email') }}</strong></div>
          <div><span>办公电话<FieldHelpTooltip :help="help.phone" /></span><strong>{{ display(selectedContact, 'office_phone', 'officePhone') }}</strong></div>
          <div><span>关系<FieldHelpTooltip :help="help.relation" /></span><strong>{{ display(selectedContact, 'relation_type', 'relationType', 'reports_to_id') }}</strong></div>
          <div><span>采购阶段<FieldHelpTooltip :help="help.purchaseStage" /></span><strong>{{ display(selectedContact, 'lead_stage', 'purchase_stage', 'purchaseStage') }}</strong></div>
          <div><span>联系人状态<FieldHelpTooltip :help="help.status" /></span><strong>{{ contactStatus(selectedContact) }}</strong></div>
          <div><span>内容类型兴趣<FieldHelpTooltip :help="help.contentInterest" /></span><strong>{{ display(selectedContact, 'top_content_types', 'contentInterest') }}</strong></div>
          <div><span>产品兴趣<FieldHelpTooltip :help="help.productInterest" /></span><strong>{{ display(selectedContact, 'product_interests', 'productInterest') }}</strong></div>
          <div><span>活跃度 / 合作意向<FieldHelpTooltip :help="help.activityIntent" /></span><strong>{{ activityLabel(selectedContact) }} / {{ display(selectedContact, 'display_intent_level', 'intent_level', 'cooperationIntent') }}</strong></div>
          <div><span>数据来源</span><strong>{{ sourceText(selectedContact) }}</strong></div>
          <div><span>偏好触达<FieldHelpTooltip :help="help.preferredChannel" /></span><strong>{{ display(selectedContact, 'preferred_channel', 'preferredChannel') }}</strong></div>
          <div><span>linkflow ID</span><strong>{{ display(selectedContact, 'linkflow_contact_id') }}</strong></div>
        </div>

        <div class="contact-playbook">
          <div>
            <span>推进方式<FieldHelpTooltip :help="help.playbook" /></span>
            <p>{{ recommendDisplay(selectedContact, 'push_way', 'recommend_way') }}</p>
          </div>
          <div>
            <span>推进话术<FieldHelpTooltip :help="help.playbook" /></span>
            <p>{{ recommendDisplay(selectedContact, 'push_script', 'recommend_script') }}</p>
          </div>
        </div>

        <div class="contact-behavior">
          <div class="contact-behavior-title">
            <span>该人的互动行为<FieldHelpTooltip :help="help.behavior" align="end" /></span>
            <small>近14天/全量历史行为</small>
          </div>
          <div class="contact-behavior-stats">
            <span>历史互动 {{ selectedContact.interaction_count || 0 }}</span>
            <span>近30天 {{ selectedContact.interaction_count_30d || 0 }}</span>
            <span>高价值 {{ selectedContact.high_value_count || 0 }}</span>
            <span>最近 {{ formatTime(selectedContact.last_interaction_time) }}</span>
          </div>
        </div>
      </aside>
    </div>

    <div v-else class="text-center py-12 text-[var(--muted)]">
      暂无匹配的联系人
    </div>
  </div>
</template>

<style scoped>
.contacts-layout {
  display: grid;
  grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.05fr);
  gap: 16px;
  align-items: start;
}

.contacts-list-panel,
.contact-detail-panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}

.contacts-list-panel {
  overflow: hidden;
}

.contacts-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.contacts-list-header b {
  color: var(--brand);
}

.contact-list-row {
  display: grid;
  width: 100%;
  grid-template-columns: 28px minmax(0, 1fr) 68px;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  text-align: left;
  transition: background-color .15s ease, border-color .15s ease;
}

.contact-list-row:hover,
.contact-list-row.active {
  background: rgba(90, 167, 255, .10);
}

.contact-list-row.active {
  box-shadow: inset 3px 0 0 var(--brand);
}

.contact-rank {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(90, 167, 255, .14);
  color: var(--text);
  font-size: 12px;
  font-weight: 800;
}

.contact-row-main {
  min-width: 0;
}

.contact-row-title,
.contact-row-sub,
.contact-row-meta {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-row-title {
  color: var(--text);
}

.contact-row-title b {
  font-size: 14px;
}

.contact-row-title em {
  margin-left: 8px;
  border: 1px solid rgba(90, 167, 255, .35);
  border-radius: 999px;
  padding: 1px 7px;
  color: var(--brand);
  font-size: 11px;
  font-style: normal;
}

.contact-row-sub,
.contact-row-meta {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.contact-row-score {
  text-align: right;
}

.contact-row-score b {
  display: block;
  color: var(--brand);
  font-size: 18px;
  line-height: 1.1;
}

.contact-row-score small {
  color: var(--muted);
  font-size: 10px;
}

.contact-detail-panel {
  padding: 18px;
}

.contact-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 14px;
}

.contact-detail-header h3 {
  margin: 0;
  color: var(--text);
  font-size: 18px;
  font-weight: 800;
}

.contact-detail-header p {
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
}

.contact-detail-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.contact-detail-badges span,
.contact-behavior-stats span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--muted);
  font-size: 11px;
}

.contact-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 22px;
  padding: 16px 0;
}

.contact-detail-grid > div > span,
.contact-playbook > div > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.3;
  white-space: nowrap;
}

.contact-detail-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.contact-playbook {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(90, 167, 255, .06);
  padding: 14px;
}

.contact-playbook p {
  margin-top: 5px;
  color: var(--text);
  font-size: 13px;
  line-height: 1.7;
}

.contact-behavior {
  margin-top: 14px;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}

.contact-behavior-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  color: var(--text);
  font-size: 13px;
  font-weight: 800;
}

.contact-behavior-title small {
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
}

.contact-behavior-stats {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 1100px) {
  .contacts-layout {
    grid-template-columns: 1fr;
  }
}
</style>
