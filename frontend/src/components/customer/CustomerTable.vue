<script setup>
import { useRouter } from 'vue-router'
import FieldHelpTooltip from './FieldHelpTooltip.vue'
import { customerFieldHelp } from './fieldHelpConfig'

const props = defineProps({
  customers: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  keyAccountMode: {
    type: Boolean,
    default: false,
  },
})

const router = useRouter()

const stageColors = {
  '问题识别': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '解决方案探索': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '需求构建': 'bg-green-500/20 text-green-400 border-green-500/30',
}

const intentColors = {
  '高': 'bg-green-500/20 text-green-400 border-green-500/30',
  '中': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '低': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const channelLabels = {
  email: '邮件',
  web: '官网',
  event: '活动',
  wechat: '微信',
}

function getStageClass(stage) {
  return stageColors[stage] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
}

function getIntentClass(intent) {
  return intentColors[intent] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
}

function formatInteractionDate(value) {
  if (!value) return '-'
  return String(value).slice(0, 10) || '-'
}

function formatInteractionChannel(value) {
  if (!value) return ''
  return channelLabels[value] || value
}

function handleRowClick(customer) {
  if (props.keyAccountMode) return
  router.push(`/customers/${customer.id}`)
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] overflow-hidden backdrop-blur">
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead>
          <tr class="border-b border-[var(--line)] bg-white/5">
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              客户名称
              <FieldHelpTooltip :help="customerFieldHelp.customerName" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              专项/行业
              <FieldHelpTooltip :help="customerFieldHelp.projectIndustry" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              采购阶段
              <FieldHelpTooltip :help="customerFieldHelp.purchaseStage" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              关键角色覆盖
              <FieldHelpTooltip :help="customerFieldHelp.roleCoverage" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              合作意向
              <FieldHelpTooltip :help="customerFieldHelp.intent" align="end" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">
              最近互动
              <FieldHelpTooltip :help="customerFieldHelp.lastInteraction" align="end" />
            </th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="7" class="px-4 py-8 text-center text-[var(--muted)]">
              <div class="flex items-center justify-center gap-2">
                <span class="animate-spin">⏳</span>
                加载中...
              </div>
            </td>
          </tr>
          <tr v-else-if="!customers || customers.length === 0">
            <td colspan="7" class="px-4 py-8 text-center text-[var(--muted)]">
              暂无数据
            </td>
          </tr>
          <tr
            v-else
            v-for="customer in customers"
            :key="customer.id"
            @click="handleRowClick(customer)"
            class="border-b border-[var(--line)] transition-colors"
            :class="keyAccountMode ? 'cursor-default' : 'cursor-pointer hover:bg-white/5'"
          >
            <td class="px-4 py-3">
              <div class="font-medium text-[var(--text)]">{{ customer.customer_name }}</div>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--muted)]">{{ customer.campaign_tag }}</div>
              <div v-if="customer.industry" class="text-xs text-[var(--muted)]/70">{{ customer.industry }}</div>
            </td>
            <td class="px-4 py-3">
              <span
                v-if="!keyAccountMode && customer.purchase_stage"
                class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
                :class="getStageClass(customer.purchase_stage)"
              >
                {{ customer.purchase_stage }}
              </span>
              <span v-else class="text-[var(--muted)]">-</span>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--text)]">{{ customer.role_coverage || '-' }}</div>
            </td>
            <td class="px-4 py-3">
              <span
                v-if="customer.intent_score !== null && customer.intent_score !== undefined"
                class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
                :class="getIntentClass(customer.intent_level)"
              >
                {{ customer.intent_score }}
              </span>
              <span v-else class="text-[var(--muted)]">-</span>
              <div v-if="!keyAccountMode" class="mt-1 text-xs text-[var(--muted)]">
                {{ customer.intent_level || '-' }}合作意向 · 互动{{ customer.interaction_count_total || 0 }}次
              </div>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--muted)]">{{ formatInteractionDate(customer.last_interaction_time) }}</div>
              <div v-if="customer.last_interaction_time" class="mt-1 text-xs text-[var(--muted)]/80">
                {{ formatInteractionChannel(customer.last_interaction_channel) || '-' }}
              </div>
            </td>
            <td class="px-4 py-3">
              <span v-if="keyAccountMode" class="text-sm text-[var(--muted)]">-</span>
              <button
                v-else
                @click.stop="handleRowClick(customer)"
                class="text-sm text-[var(--brand)] hover:underline"
              >
                打开
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
