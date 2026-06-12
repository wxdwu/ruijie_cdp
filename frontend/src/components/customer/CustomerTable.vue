<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  customers: {
    type: Array,
    default: () => [],
  },
  loading: {
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

function getStageClass(stage) {
  return stageColors[stage] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
}

function getIntentClass(intent) {
  return intentColors[intent] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
}

function handleRowClick(customer) {
  router.push(`/customers/${customer.id}`)
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] overflow-hidden backdrop-blur">
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead>
          <tr class="border-b border-[var(--line)] bg-white/5">
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">客户名称</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">专项/行业</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">采购阶段</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">关键角色覆盖</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">合作意向</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-[var(--muted)]">最近互动</th>
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
            class="border-b border-[var(--line)] cursor-pointer transition-colors hover:bg-white/5"
          >
            <td class="px-4 py-3">
              <div class="font-medium text-[var(--text)]">{{ customer.customer_name }}</div>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--muted)]">{{ customer.campaign_tag }}</div>
              <div class="text-xs text-[var(--muted)]/70">{{ customer.industry }}</div>
            </td>
            <td class="px-4 py-3">
              <span
                class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
                :class="getStageClass(customer.purchase_stage)"
              >
                {{ customer.purchase_stage }}
              </span>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--text)]">{{ customer.role_coverage || '-' }}</div>
            </td>
            <td class="px-4 py-3">
              <span
                v-if="customer.intent_level"
                class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
                :class="getIntentClass(customer.intent_level)"
              >
                {{ customer.intent_level }}
              </span>
              <span v-else class="text-[var(--muted)]">-</span>
            </td>
            <td class="px-4 py-3">
              <div class="text-sm text-[var(--muted)]">{{ customer.last_interaction_time || '-' }}</div>
            </td>
            <td class="px-4 py-3">
              <button
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
