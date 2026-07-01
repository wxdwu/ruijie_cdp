<script setup>
import { computed } from 'vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  intent: { type: String, default: '-' },
  intentScore: { type: [Number, String], default: null },
  interactionCount: { type: Number, default: 0 },
  stage: { type: String, default: '-' },
  keyRoles: { type: String, default: '-' },
  contacts: { type: Array, default: () => [] },
  opportunityCount: { type: Number, default: 0 },
  opportunityAmount: { type: [Number, String], default: null },
})

function formatCurrencyWan(value) {
  if (value === null || value === undefined || value === '') return '0'
  const number = Number(value)
  if (!Number.isFinite(number)) return '0'
  return (number / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })
}

const intentColors = {
  '高': 'bg-green-500/20 text-green-400 border-green-500/30',
  '中': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '低': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const stageColors = {
  '问题识别': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '解决方案探索': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '需求构建': 'bg-green-500/20 text-green-400 border-green-500/30',
}

const requiredRoles = ['拍板者', '决策者', '评估者', '采购推动者']

function normalizeKeyRole(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.includes('拍板')) return '拍板者'
  if (text.includes('决策')) return '决策者'
  if (text.includes('评估') || text.includes('技术')) return '评估者'
  if (text.includes('采购') || text.includes('推动')) return '采购推动者'
  return ''
}

const coveredRoleSet = computed(() => {
  const roles = new Set()
  props.contacts.forEach(contact => {
    ;[contact.role_category, contact.purchase_role].forEach(value => {
      const role = normalizeKeyRole(value)
      if (role) roles.add(role)
    })
  })

  if (!roles.size && props.keyRoles === '全') {
    requiredRoles.forEach(role => roles.add(role))
  }

  return roles
})

const missingRoles = computed(() => requiredRoles.filter(role => !coveredRoleSet.value.has(role)))

const help = {
  intent: {
    title: '意向度评分',
    type: 'calc',
    fields: [
      {
        type: 'calc',
        variable: 'intent_score',
        meaning: '合作意向分',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'intent_score(合作意向分)',
        calculation: 'ETL 计算：intent_score = min(100, interaction_count_30d × 2 + (active_opp_count > 0 ? 20 : 0) + (contact_count >= 3 ? 10 : contact_count × 3))。即近30天每次互动加2分，有在途商机加20分，联系人数量最多加10分，最终封顶100分。',
        timeRule: 'interaction_count_30d 为近30天互动次数；详情页展示时会按当前日期往前30天动态覆盖近30天互动数。',
        emptyState: '无意向信号时显示 0。',
      },
      {
        type: 'calc',
        variable: 'intent_level',
        meaning: '合作意向等级',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'intent_level(合作意向等级)',
        calculation: 'ETL 映射：近30天互动次数 >= 10 且存在在途商机时为“高”；近30天互动次数 >= 3 时为“中”；历史总互动次数 > 0 时为“低”；否则为“无”。',
        emptyState: '无意向等级时显示无或 -。',
      },
      {
        type: 'src',
        variable: 'interaction_count_30d',
        meaning: '近30天互动次数',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'interaction_count_30d(近30天互动次数)',
        calculation: '用于意向分计算的互动活跃度信号；当前详情页按 dws_interaction_detail.event_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) 重新计算展示值。',
        timeRule: '以当前日期为基准向前推30天。',
        emptyState: '无互动信号时显示 0 次。',
      },
    ],
  },
  stage: {
    title: '采购阶段',
    type: 'calc',
    meaning: '客户当前所处采购阶段。',
    sourceTables: 'dws_customer_360',
    sourceFields: 'dws_customer_360.purchase_stage',
    calculation: '页面直接展示 dws_customer_360.purchase_stage；该字段由 ETL 从 ods_crm_opportunity_day.customer_stage / forecast_type 等上游字段聚合到客户维度。',
    emptyState: '无采购阶段时显示未知。',
  },
  roleCoverage: {
    title: '关键人覆盖',
    type: 'calc',
    meaning: '判断客户是否覆盖拍板者、决策者、评估者、采购推动者四类关键角色。',
    sourceTables: 'dws_customer_360, dws_contact_360',
    sourceFields: 'dws_customer_360.role_coverage, dws_contact_360.role_category, dws_contact_360.purchase_role',
    calculation: '卡片展示按联系人 dws_contact_360.role_category / purchase_role 归一化后的覆盖数/4，并列出缺失角色；dws_customer_360.role_coverage 作为客户级聚合状态参考。',
    emptyState: '没有可识别关键角色时显示 0/4，并列出拍板者、决策者、评估者、采购推动者均缺失。',
  },
  activeOpportunity: {
    title: '在途商机',
    fields: [
      {
        type: 'src',
        variable: 'funnel_opp_count',
        meaning: '在途商机数',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'funnel_opp_count(漏斗商机数)',
        calculation: '-',
        emptyState: '无数据时显示 0。',
      },
      {
        type: 'src',
        variable: 'active_opp_amount',
        meaning: '在途商机金额',
        sourceTable: 'dws_customer_360',
        sourceFieldDisplay: 'active_opp_amount(在途商机总金额)',
        calculation: '-',
        emptyState: '无数据时显示 0。',
      },
      {
        type: 'calc',
        variable: 'overdue_task_count',
        meaning: '超期任务',
        sourceTable: '-',
        sourceFieldDisplay: '-',
        calculation: '当前数据库未落地任务/拜访/跟进记录明细表，暂无法计算。',
        emptyState: '无字段时显示字段待填充。',
      },
    ],
  },
}
</script>

<template>
  <div class="grid grid-cols-4 gap-4">
    <!-- 合作意向 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">合作意向<FieldHelpTooltip :help="help.intent" /></div>
      <div class="text-2xl font-bold text-[var(--text)]">
        <span v-if="intentScore !== null && intentScore !== undefined" class="mr-2 align-middle">
          {{ intentScore }}
        </span>
        <span
          v-if="intent !== '-'"
          class="inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium"
          :class="intentColors[intent] || intentColors['低']"
        >
            {{ intent }}
        </span>
        <span v-else class="text-[var(--muted)]">-</span>
      </div>
      <div class="text-xs text-[var(--muted)] mt-1">近30天互动 {{ interactionCount }} 次</div>
    </div>

    <!-- 采购阶段 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">采购阶段<FieldHelpTooltip :help="help.stage" /></div>
      <div class="text-lg font-bold text-[var(--text)]">
        <span
          class="inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium"
          :class="stage && stage !== '-' ? (stageColors[stage] || 'bg-gray-500/20 text-gray-400 border-gray-500/30') : 'bg-gray-500/20 text-gray-400 border-gray-500/30'"
        >
          {{ stage && stage !== '-' ? stage : '未知' }}
        </span>
      </div>
    </div>

    <!-- 关键角色覆盖 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">关键角色覆盖<FieldHelpTooltip :help="help.roleCoverage" /></div>
      <div class="text-2xl font-bold text-[var(--text)]">
        <span class="text-amber-400">{{ coveredRoleSet.size }}</span>/{{ requiredRoles.length }}
      </div>
      <div class="mt-1 text-xs text-[var(--muted)]">
        <span v-if="missingRoles.length">缺 {{ missingRoles.join('、') }}</span>
        <span v-else>关键角色已覆盖</span>
      </div>
    </div>

    <!-- 在途商机 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">在途商机<FieldHelpTooltip :help="help.activeOpportunity" align="end" /></div>
      <div class="flex items-baseline gap-6 text-[var(--text)]">
        <span class="text-2xl font-bold">{{ opportunityCount }}个</span>
        <span class="text-xs font-bold">商机金额 {{ formatCurrencyWan(opportunityAmount) }}万</span>
      </div>
      <div class="mt-2 flex items-center gap-2 text-xs font-bold text-[var(--text)]">
        <span>超期任务</span>
        <span class="inline-flex items-center rounded-full border border-red-400/50 bg-red-400/10 px-2 py-0.5 text-[11px] font-bold leading-snug text-red-600">
          字段待填充
        </span>
      </div>
    </div>
  </div>
</template>
