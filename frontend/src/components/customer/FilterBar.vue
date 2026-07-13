<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { customerApi } from '../../api'

const emit = defineEmits(['apply'])

const keyword = ref('')
const industry = ref('')
const selectedRegion = ref('')
const selectedOwner = ref('')
const specialProject = ref('企业彩光ICT')
const attribute = ref('')
const channel = ref('')
const interaction_min = ref(null)
const interaction_period = ref(30) // 默认30天

const industries = ref([])
const regions = ref([])
const owners = ref([])
const availableChannels = ref([])
const isKeyAccountSelection = computed(() => specialProject.value === '重客')
const AUTO_APPLY_DELAY = 400
let applyTimer = null
let filterOptionsRequestId = 0

const channelLabels = {
  email: '邮件',
  web: '官网',
  event: '直播/活动',
  wechat: '微信',
  other: '其他',
}
const channels = computed(() => [
  { value: '', label: '全部' },
  ...availableChannels.value.map(value => ({ value, label: channelLabels[value] || value })),
])

const periodOptions = [
  { value: 30, label: '近30天' },
  { value: 60, label: '近60天' },
  { value: 90, label: '近90天' },
  { value: 180, label: '近180天' },
  { value: 365, label: '近1年' },
  { value: 1095, label: '近3年' },
]

async function fetchFilterOptions(project = specialProject.value) {
  const requestId = ++filterOptionsRequestId
  try {
    const res = await customerApi.filterOptions({ special_project: project || undefined })
    if (requestId !== filterOptionsRequestId) return
    industries.value = res.industries || []
    regions.value = res.regions || []
    owners.value = res.owners || []
    availableChannels.value = res.channels || []
    if (industry.value && !industries.value.includes(industry.value)) industry.value = ''
    if (selectedRegion.value && !regions.value.includes(selectedRegion.value)) selectedRegion.value = ''
    if (selectedOwner.value && !owners.value.includes(selectedOwner.value)) selectedOwner.value = ''
    if (channel.value && !availableChannels.value.includes(channel.value)) channel.value = ''
  } catch (e) {
    console.error('Failed to fetch filter options:', e)
  }
}

function handleApply() {
  emit('apply', {
    keyword: keyword.value.trim(),
    special_project: specialProject.value,
    industry: industry.value,
    region: selectedRegion.value,
    region_keyword: '',
    owner: selectedOwner.value,
    owner_keyword: '',
    interaction_min: interaction_min.value,
    interaction_period: interaction_period.value,
    attribute: attribute.value,
    channel: channel.value,
  })
}

function cancelScheduledApply() {
  if (applyTimer === null) return
  window.clearTimeout(applyTimer)
  applyTimer = null
}

function applyNow() {
  cancelScheduledApply()
  handleApply()
}

function scheduleApply() {
  cancelScheduledApply()
  applyTimer = window.setTimeout(() => {
    applyTimer = null
    handleApply()
  }, AUTO_APPLY_DELAY)
}

watch(specialProject, async (value, previousValue) => {
  if (value === '重客') {
    attribute.value = 'heavy'
  } else if (previousValue === '重客') {
    attribute.value = ''
  }
  await fetchFilterOptions(value)
  if (value !== specialProject.value) return
  applyNow()
})

onMounted(() => {
  fetchFilterOptions()
})

onBeforeUnmount(() => {
  cancelScheduledApply()
})
</script>

<template>
  <div class="relative z-40 overflow-visible rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 backdrop-blur">
    <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-4">
      <!-- 专项 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">专项</label>
        <select
          v-model="specialProject"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部</option>
          <option value="企业彩光ICT">企业彩光ICT</option>
          <option value="重客">重客</option>
        </select>
      </div>

      <!-- 客户关键词 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">客户关键词</label>
        <input
          v-model="keyword"
          type="text"
          placeholder="输入客户名称..."
          @input="scheduleApply"
          @keyup.enter="applyNow"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
      </div>

      <!-- 行业 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">行业</label>
        <select
          v-model="industry"
          @change="applyNow"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部行业</option>
          <option v-for="item in industries" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 省份 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">省份</label>
        <select
          v-model="selectedRegion"
          @change="applyNow"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部省份</option>
          <option v-for="item in regions" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 负责人 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">负责人</label>
        <select
          v-model="selectedOwner"
          @change="applyNow"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部负责人</option>
          <option v-for="item in owners" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 互动次数筛选 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">互动次数 ≥</label>
        <div class="grid grid-cols-[minmax(0,1fr)_3.5rem] gap-1">
          <select
            v-model.number="interaction_period"
            @change="applyNow"
            class="customer-filter-select min-w-0 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-2 py-2 text-xs text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
          >
            <option v-for="p in periodOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
          <input
            v-model.number="interaction_min"
            type="number"
            min="0"
            placeholder="0"
            @input="scheduleApply"
            @keyup.enter="applyNow"
            class="min-w-0 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-2 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
          />
        </div>
      </div>

      <!-- 是否为重客 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客专项固定为是重客' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">是否为重客</label>
        <select
          v-model="attribute"
          :disabled="isKeyAccountSelection"
          @change="applyNow"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部</option>
          <option value="heavy">是重客</option>
          <option value="non_heavy">不是重客</option>
        </select>
      </div>

      <!-- 互动方式 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">互动方式</label>
        <select
          v-model="channel"
          @change="applyNow"
          class="customer-filter-select rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option v-for="item in channels" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
    </div>

  </div>
</template>

<style>
.customer-filter-select,
.customer-filter-select::picker(select) {
  appearance: base-select;
}

.customer-filter-select::picker(select) {
  max-height: 15rem;
  margin-block: 0.25rem;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: 0;
  background: var(--bg1);
  color: var(--text);
  box-shadow: var(--shadow);
}

.customer-filter-select option {
  padding: 0.5rem 0.75rem;
  color: var(--text);
  font-size: 0.875rem;
}

.customer-filter-select option:hover,
.customer-filter-select option:focus-visible {
  background: var(--surface-hover);
}

.customer-filter-select option:checked {
  background: color-mix(in srgb, var(--brand) 28%, var(--bg1));
}

.customer-filter-select option::checkmark {
  display: none;
}
</style>
