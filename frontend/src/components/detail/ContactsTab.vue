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

const roles = ['决策者', '拍板者', '技术评估者', '使用者', '其他']

const filteredContacts = computed(() => {
  let result = props.contacts

  if (searchQuery.value) {
    result = result.filter(c =>
      c.contact_name?.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      c.mobile?.includes(searchQuery.value)
    )
  }

  if (selectedRole.value) {
    result = result.filter(c => c.role_category === selectedRole.value)
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
    <div class="flex items-center gap-4">
      <div class="flex-1">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索联系人姓名..."
          class="w-full rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--brand)]"
        />
      </div>
      <div class="flex gap-2">
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
