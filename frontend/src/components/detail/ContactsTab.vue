<script setup>
import { ref, computed } from 'vue'
import AiPriorityContact from './AiPriorityContact.vue'
import ContactCard from './ContactCard.vue'

const props = defineProps({
  contacts: { type: Array, default: () => [] },
  priorityContact: { type: Object, default: () => ({}) },
  // AI 推荐联系人列表（从 priority-contact API 获取）
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

const roles = ['决策者', '拍板者', '技术评估者', '使用者', '其他']

const stages = computed(() => {
  return [...new Set(props.contacts.map(c => c.purchase_stage || c.purchaseStage).filter(Boolean))]
})

const filteredContacts = computed(() => {
  let result = props.contacts

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(c =>
      c.contact_name?.toLowerCase().includes(query) ||
      c.mobile?.includes(searchQuery.value) ||
      c.position?.toLowerCase().includes(query) ||
      c.department?.toLowerCase().includes(query)
    )
  }

  if (selectedRole.value) {
    result = result.filter(c => c.role_category === selectedRole.value)
  }

  if (selectedStage.value) {
    result = result.filter(c => (c.purchase_stage || c.purchaseStage) === selectedStage.value)
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
    result = result.filter(c => c.is_vip_role || c.isVipRole__c || c.role_category === '拍板者' || c.role_category === '决策者')
  }

  return result
})
</script>

<template>
  <div class="space-y-6">
    <!-- AI Priority Contact Banner -->
    <AiPriorityContact
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
      <div class="flex flex-wrap gap-2">
        <button
          v-for="role in roles"
          :key="role"
          @click="selectedRole = selectedRole === role ? '' : role"
          class="rounded-lg border px-3 py-2 text-sm transition-colors"
          :class="
            selectedRole === role
              ? 'bg-[var(--brand)] text-white border-[var(--brand)]'
              : 'border-[var(--line)] bg-white/5 text-[var(--text)] hover:bg-white/10'
          "
        >
          {{ role }}
        </button>
      </div>
    </div>

    <!-- Contact Cards Grid -->
    <div class="grid grid-cols-2 gap-4">
      <ContactCard
        v-for="contact in filteredContacts"
        :key="contact.id"
        :contact="contact"
      />
    </div>

    <!-- Empty State -->
    <div v-if="filteredContacts.length === 0" class="text-center py-12 text-[var(--muted)]">
      暂无匹配的联系人
    </div>
  </div>
</template>
