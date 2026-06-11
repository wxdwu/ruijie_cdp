<script setup>
import { ref, onMounted } from 'vue'
import { customerApi } from '../../api'

const emit = defineEmits(['apply'])

const specialProject = ref('企业彩光ICT')
const keyword = ref('')
const industry = ref('')
const owner = ref('')
const interactionCount = ref(null)
const interactionType = ref('')

const industries = ref([])
const owners = ref([])
const loading = ref(false)

const interactionTypes = [
  { value: '', label: '全部' },
  { value: 'live', label: '直播' },
  { value: 'email', label: '邮件' },
  { value: 'website', label: '官网' },
]

async function fetchFilterOptions() {
  try {
    const res = await customerApi.filterOptions()
    industries.value = res.industries || []
    owners.value = res.owners || []
  } catch (e) {
    console.error('Failed to fetch filter options:', e)
  }
}

function handleApply() {
  emit('apply', {
    specialProject: specialProject.value,
    keyword: keyword.value,
    industry: industry.value,
    owner: owner.value,
    interactionCount: interactionCount.value,
    interactionType: interactionType.value,
  })
}

onMounted(() => {
  fetchFilterOptions()
})
</script>

<template>
  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 backdrop-blur">
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <!-- 专项 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">专项</label>
        <select
          v-model="specialProject"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="企业彩光ICT">企业彩光ICT</option>
        </select>
      </div>

      <!-- 客户关键词 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">客户关键词</label>
        <input
          v-model="keyword"
          type="text"
          placeholder="输入客户名称..."
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
      </div>

      <!-- 行业 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">行业</label>
        <select
          v-model="industry"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部行业</option>
          <option v-for="item in industries" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 负责人 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">负责人</label>
        <select
          v-model="owner"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部负责人</option>
          <option v-for="item in owners" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 近30天互动 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">近30天互动 ≥</label>
        <input
          v-model.number="interactionCount"
          type="number"
          min="0"
          placeholder="0"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
      </div>

      <!-- 互动方式 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">互动方式</label>
        <select
          v-model="interactionType"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option v-for="item in interactionTypes" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <button
        @click="handleApply"
        :disabled="loading"
        class="rounded-lg bg-[var(--brand)] px-5 py-2 text-sm font-medium text-white transition-colors hover:brightness-110 disabled:opacity-50"
      >
        {{ loading ? '加载中...' : '应用筛选' }}
      </button>
    </div>
  </div>
</template>
