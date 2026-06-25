<script setup>
import { computed } from 'vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  // 单个优先推进对象，包含 contact_name, reason, recommend_way, recommend_script 等
  recommendation: {
    type: Object,
    default: null,
  },
  // 兼容旧接口数组结构
  recommendations: {
    type: Array,
    default: () => [],
  },
  // 数据来源标记
  source: {
    type: String,
    default: "rule",
  },
})

const priorityContact = computed(() => {
  return props.recommendation || props.recommendations?.[0] || null
})

const roleText = computed(() => {
  const contact = priorityContact.value
  return contact?.role_category || contact?.purchase_role || '联系人'
})

const help = {
  title: 'AI优先推进对象',
  type: 'calc',
  meaning: '从当前客户联系人中选出一名最适合优先推进的联系人，并生成推进原因、方式和话术。',
  sourceTables: 'dws_contact_360, dws_customer_360, dws_interaction_detail',
  sourceFields: 'dws_contact_360.role_category, dws_contact_360.purchase_role, dws_contact_360.interaction_count_30d, dws_contact_360.last_interaction_time, dws_contact_360.mobile, dws_contact_360.email, dws_contact_360.product_interests, dws_contact_360.top_content_types, dws_customer_360.purchase_stage, dws_customer_360.forecast_type, dws_customer_360.highest_stage_opp, dws_customer_360.industry, dws_customer_360.campaign_tag, dws_interaction_detail.is_high_value',
  calculation: '规则评分为角色影响力35%、近30天互动25%、最近互动20%、信息完整度10%、意向等级10%，activity_level 少量加分；按总分取 Top1。推荐话术会将 purchase_stage 映射为适合销售沟通的阶段表达，主题固定为方案。',
  emptyState: '缺少阶段时显示当前推进阶段；缺少案例场景时显示同类客户；无联系人时显示暂无联系人。',
}
</script>

<template>
  <div class="rounded-xl border border-[var(--brand)]/30 bg-[var(--brand)]/5 px-5 py-4">
    <div class="mb-4 flex items-start justify-between gap-4">
      <div class="flex min-w-0 items-center gap-2">
        <span class="text-lg">🤖</span>
        <span class="text-base font-semibold text-[var(--text)]">
          AI优先推进对象
        </span>
        <FieldHelpTooltip :help="help" />
      </div>

      <div
        v-if="priorityContact"
        class="shrink-0 rounded-full border border-emerald-300/60 bg-emerald-100/40 px-3 py-1 text-lg font-bold text-emerald-400"
      >
        {{ priorityContact.relevance_score || '-' }}
      </div>
    </div>

    <div v-if="priorityContact" class="space-y-1.5 text-sm leading-7 text-[var(--muted)]">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <span class="text-xl font-bold leading-tight text-[var(--text)]">
          {{ priorityContact.contact_name || '未命名联系人' }}
        </span>
        <span
          class="inline-flex items-center rounded-full border border-[var(--brand)]/35 bg-[var(--brand)]/10 px-2.5 py-0.5 text-xs font-semibold text-[var(--brand)]"
        >
          {{ roleText }}
        </span>
      </div>
      <div>
        <span class="font-semibold text-[var(--text)]">原因：</span>{{ priorityContact.reason || '-' }}
      </div>
      <div>
        <span class="font-semibold text-[var(--text)]">方式：</span>{{ priorityContact.recommend_way || '-' }}
      </div>
      <div>
        <span class="font-semibold text-[var(--text)]">推荐话术：</span>{{ priorityContact.recommend_script || '-' }}
      </div>
    </div>

    <div v-else class="py-4 text-center text-sm text-[var(--muted)]">
      暂无联系人
    </div>
  </div>
</template>
