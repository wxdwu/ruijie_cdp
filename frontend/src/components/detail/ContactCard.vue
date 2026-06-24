<script setup>
const props = defineProps({
  contact: { type: Object, default: () => ({}) },
})

const roleColors = {
  '决策者': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  '拍板者': 'bg-red-500/20 text-red-400 border-red-500/30',
  '技术评估者': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '使用者': 'bg-green-500/20 text-green-400 border-green-500/30',
  '其他': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const activityColors = {
  '高': 'bg-green-500/20 text-green-400',
  'medium': 'bg-green-500/20 text-green-400',
  '中': 'bg-yellow-500/20 text-yellow-400',
  '低': 'bg-gray-500/20 text-gray-400',
  'none': 'bg-gray-500/20 text-gray-400',
}

function formatTime(val) {
  if (!val) return '-'
  try {
    const d = new Date(val)
    return d.toLocaleDateString('zh-CN')
  } catch (e) { return val }
}

function display(...keys) {
  for (const key of keys) {
    const value = props.contact?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return '-'
}
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 hover:border-[var(--brand)]/50 transition-colors">
    <div class="flex items-start justify-between mb-4">
      <div>
        <div class="text-lg font-medium text-[var(--text)]">{{ contact.contact_name || '未命名' }}</div>
        <div class="text-sm text-[var(--muted)]">
          {{ contact.position || '-' }} · {{ contact.department || '-' }}
        </div>
      </div>
      <div class="flex gap-2">
        <span
          v-if="contact.role_category"
          class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium"
          :class="roleColors[contact.role_category] || roleColors['其他']"
        >
          {{ contact.role_category }}
        </span>
        <span
          v-if="contact.activity_level"
          class="inline-flex items-center rounded-full px-2 py-0.5 text-xs"
          :class="activityColors[contact.activity_level] || activityColors['低']"
        >
          {{ contact.activity_level }}
        </span>
      </div>
    </div>
    <div class="space-y-2 mb-4">
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">手机</span>
        <span class="text-[var(--text)]">{{ contact.mobile || '-' }}</span>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--muted)]">邮箱</span>
        <span class="text-[var(--text)]">{{ contact.email || '-' }}</span>
      </div>
      <div class="grid grid-cols-2 gap-x-4 gap-y-2 pt-2 text-xs">
        <div><span class="text-[var(--muted)]">办公电话</span><div class="text-[var(--text)]">{{ display('office_phone', 'officePhone') }}</div></div>
        <div><span class="text-[var(--muted)]">关系</span><div class="text-[var(--text)]">{{ display('relation_type', 'relationType', 'reports_to_id') }}</div></div>
        <div><span class="text-[var(--muted)]">采购阶段</span><div class="text-[var(--text)]">{{ display('purchase_stage', 'purchaseStage') }}</div></div>
        <div><span class="text-[var(--muted)]">联系人状态</span><div class="text-[var(--text)]">{{ display('Status__c', 'status', 'contact_validity') }}</div></div>
        <div><span class="text-[var(--muted)]">内容类型兴趣</span><div class="text-[var(--text)]">{{ display('top_content_types', 'contentInterest') }}</div></div>
        <div><span class="text-[var(--muted)]">产品兴趣</span><div class="text-[var(--text)]">{{ display('product_interests', 'productInterest') }}</div></div>
        <div><span class="text-[var(--muted)]">数据来源</span><div class="text-[var(--text)]">{{ display('source_table', 'dataSource') }}</div></div>
        <div><span class="text-[var(--muted)]">偏好触达</span><div class="text-[var(--text)]">{{ display('preferred_channel', 'preferredChannel') }}</div></div>
      </div>
      <div class="rounded-lg border border-[var(--line)] bg-white/5 p-3 text-xs">
        <div class="mb-1 text-[var(--muted)]">推进方式</div>
        <div class="text-[var(--text)]">{{ display('push_way', 'recommend_way') }}</div>
        <div class="mb-1 mt-3 text-[var(--muted)]">推进话术</div>
        <div class="leading-5 text-[var(--text)]">{{ display('push_script', 'recommend_script') }}</div>
      </div>
    </div>
    <div class="flex items-center justify-between pt-3 border-t border-[var(--line)] text-xs">
      <span class="text-[var(--muted)]">互动 {{ contact.interaction_count || 0 }} 次</span>
      <span class="text-[var(--muted)]">最近: {{ formatTime(contact.last_interaction_time) }}</span>
    </div>
    <div class="mt-3 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
      <span class="rounded border border-[var(--line)] px-2 py-1">高价值 {{ contact.high_value_count || 0 }}</span>
      <span class="rounded border border-[var(--line)] px-2 py-1">近30天 {{ contact.interaction_count_30d || 0 }}</span>
      <span class="rounded border border-[var(--line)] px-2 py-1">活跃度 / 合作意向 {{ contact.activity_level || '-' }} / {{ contact.intent_level || '-' }}</span>
    </div>
  </div>
</template>
