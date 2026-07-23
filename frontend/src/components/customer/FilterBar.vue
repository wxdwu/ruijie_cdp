<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { customerApi } from "../../api"
import CustomerNameMultiSelect from "./CustomerNameMultiSelect.vue"
import MultiSelect from "./MultiSelect.vue"

const emit = defineEmits(["apply"])

const selectedKeyword = ref([])
const industry = ref([])
const selectedRegion = ref([])
const selectedOwner = ref([])
const specialProject = ref(["企业彩光ICT"])
const attribute = ref("")
const channel = ref([])
const interaction_min = ref(null)
const interaction_period = ref(30) // 默认30天

const industries = ref([])
const regions = ref([])
const owners = ref([])
const availableChannels = ref([])
const isKeyAccountSelection = computed(() => (
  specialProject.value.length === 1 && specialProject.value[0] === "重客"
))
const AUTO_APPLY_DELAY = 400
let applyTimer = null
let filterOptionsRequestId = 0

const channelLabels = {
  email: "邮件",
  web: "官网",
  event: "直播/活动",
  wechat: "微信",
  other: "其他",
}
const channels = computed(() =>
  availableChannels.value.map(value => ({ value, label: channelLabels[value] || value })),
)

const periodOptions = [
  { value: 30, label: "近30天" },
  { value: 60, label: "近60天" },
  { value: 90, label: "近90天" },
  { value: 180, label: "近180天" },
  { value: 365, label: "近1年" },
  { value: 1095, label: "近3年" },
]

const industryOptions = computed(() => (
  industries.value.map(item => ({ value: item, label: item }))
))
const regionOptions = computed(() => (
  regions.value.map(item => ({ value: item, label: item }))
))
const ownerOptions = computed(() => (
  owners.value.map(item => ({ value: item, label: item }))
))
const specialProjectOptions = [
  { value: "企业彩光ICT", label: "企业彩光ICT" },
  { value: "重客", label: "重客" },
]

function keepExistingValues(current, options) {
  return current.filter(v => options.includes(v))
}

async function fetchFilterOptions(project = specialProject.value) {
  const requestId = ++filterOptionsRequestId
  try {
    const res = await customerApi.filterOptions({
      special_project: Array.isArray(project) ? project : (project ? [project] : []),
    })
    if (requestId !== filterOptionsRequestId) return
    industries.value = res.industries || []
    regions.value = res.regions || []
    owners.value = res.owners || []
    availableChannels.value = res.channels || []
    // 若选项已不存在，自动移除当前已选值
    industry.value = keepExistingValues(industry.value, industries.value)
    selectedRegion.value = keepExistingValues(selectedRegion.value, regions.value)
    selectedOwner.value = keepExistingValues(selectedOwner.value, owners.value)
    channel.value = keepExistingValues(channel.value, availableChannels.value)
  } catch (e) {
    console.error("Failed to fetch filter options:", e)
  }
}

function handleApply() {
  emit("apply", {
    keyword: selectedKeyword.value,
    special_project: specialProject.value,
    industry: industry.value,
    region: selectedRegion.value,
    owner: selectedOwner.value,
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

function resetFilters() {
  selectedKeyword.value = []
  specialProject.value = ["企业彩光ICT"]
  industry.value = []
  selectedRegion.value = []
  selectedOwner.value = []
  attribute.value = ""
  channel.value = []
  interaction_min.value = null
  interaction_period.value = 30
  applyNow()
}

function handleSpecialProjectChange() {
  selectedKeyword.value = []
  if (isKeyAccountSelection.value) {
    attribute.value = "heavy"
  } else if (attribute.value === "heavy") {
    attribute.value = ""
  }
  fetchFilterOptions(specialProject.value)
  applyNow()
}

watch(specialProject, handleSpecialProjectChange)

onMounted(() => {
  fetchFilterOptions()
})

onBeforeUnmount(() => {
  cancelScheduledApply()
})
</script>

<template>
  <div class="relative z-40 overflow-visible rounded-xl border border-[var(--line)] bg-[var(--panel)] p-5 backdrop-blur">
    <!-- 一键重置筛选条件 -->
    <button
      type="button"
      @click="resetFilters"
      title="重置全部筛选条件"
      aria-label="重置筛选条件"
      class="absolute right-4 top-4 z-10 flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--line)] bg-[var(--bg1)] text-[var(--muted)] transition-all hover:rotate-180 hover:border-[var(--brand)] hover:text-[var(--brand)] active:scale-90"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4">
        <path d="M4 20 L4 10 Q4 4 10 4 L20 4" />
        <path d="M9 15 L9 10 Q9 9 10 9 L15 9" />
      </svg>
    </button>

    <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-4 pr-10">
      <!-- 专项 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">专项</label>
        <MultiSelect
          v-model="specialProject"
          :options="specialProjectOptions"
          placeholder="全部专项"
          all-label="全部"
        />
      </div>

      <!-- 客户关键词 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">客户关键词</label>
        <CustomerNameMultiSelect
          v-model="selectedKeyword"
          :special-project="specialProject"
          placeholder="全部客户"
          all-label="全部客户"
          search-placeholder="搜索客户..."
          @change="applyNow"
        />
      </div>

      <!-- 行业 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">行业</label>
        <MultiSelect
          v-model="industry"
          :options="industryOptions"
          placeholder="全部行业"
          all-label="全部行业"
          @change="applyNow"
        />
      </div>

      <!-- 省份 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">省份</label>
        <MultiSelect
          v-model="selectedRegion"
          :options="regionOptions"
          placeholder="全部省份"
          all-label="全部省份"
          searchable
          search-placeholder="搜索省份..."
          @change="applyNow"
        />
      </div>

      <!-- 负责人 -->
      <div class="flex min-w-0 flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">负责人</label>
        <MultiSelect
          v-model="selectedOwner"
          :options="ownerOptions"
          placeholder="全部负责人"
          all-label="全部负责人"
          searchable
          search-placeholder="搜索负责人..."
          @change="applyNow"
        />
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
        <MultiSelect
          v-model="channel"
          :options="channels"
          placeholder="全部互动方式"
          all-label="全部"
          @change="applyNow"
        />
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
