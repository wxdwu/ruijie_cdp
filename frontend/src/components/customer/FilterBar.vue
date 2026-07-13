<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { customerApi } from '../../api'

const emit = defineEmits(['apply'])

const keyword = ref('')
const industry = ref('')
const regionInput = ref('')
const selectedRegion = ref('')
const regionComboboxOpen = ref(false)
const regionComboboxRef = ref(null)
const regionInputRef = ref(null)
const ownerInput = ref('')
const selectedOwner = ref('')
const ownerComboboxOpen = ref(false)
const ownerComboboxRef = ref(null)
const ownerInputRef = ref(null)
const specialProject = ref('企业彩光ICT')
const attribute = ref('')
const channel = ref('')
const interaction_min = ref(null)
const interaction_period = ref(30) // 默认30天

const industries = ref([])
const regions = ref([])
const owners = ref([])
const loading = ref(false)
const isKeyAccountSelection = computed(() => specialProject.value === '重客')

const channels = [
  { value: '', label: '全部' },
  { value: 'email', label: '邮件' },
  { value: 'web', label: '官网' },
  { value: 'event', label: '直播/活动' },
  { value: 'wechat', label: '微信' },
]

const periodOptions = [
  { value: 30, label: '近30天' },
  { value: 60, label: '近60天' },
  { value: 90, label: '近90天' },
  { value: 180, label: '近180天' },
  { value: 365, label: '近1年' },
  { value: 1095, label: '近3年' },
]

const filteredOwners = computed(() => {
  const q = ownerInput.value.trim().toLowerCase()
  if (!q) return owners.value
  return owners.value.filter((item) => item.toLowerCase().includes(q))
})

const filteredRegions = computed(() => {
  const q = regionInput.value.trim().toLowerCase()
  if (!q) return regions.value
  return regions.value.filter((item) => item.toLowerCase().includes(q))
})

async function fetchFilterOptions() {
  try {
    const res = await customerApi.filterOptions()
    industries.value = res.industries || []
    regions.value = res.regions || []
    owners.value = res.owners || []
  } catch (e) {
    console.error('Failed to fetch filter options:', e)
  }
}

function openRegionCombobox() {
  if (isKeyAccountSelection.value) return
  regionComboboxOpen.value = true
}

function openRegionComboboxFromArrow() {
  if (isKeyAccountSelection.value) return
  regionComboboxOpen.value = true
  regionInputRef.value?.focus()
}

function handleRegionInput() {
  if (isKeyAccountSelection.value) return
  if (regionInput.value !== selectedRegion.value) {
    selectedRegion.value = ''
  }
  regionComboboxOpen.value = true
}

function selectRegion(value) {
  selectedRegion.value = value
  regionInput.value = value
  regionComboboxOpen.value = false
}

function clearRegion() {
  selectedRegion.value = ''
  regionInput.value = ''
  regionComboboxOpen.value = false
}

function openOwnerCombobox() {
  if (isKeyAccountSelection.value) return
  ownerComboboxOpen.value = true
}

function openOwnerComboboxFromArrow() {
  if (isKeyAccountSelection.value) return
  ownerComboboxOpen.value = true
  ownerInputRef.value?.focus()
}

function handleOwnerInput() {
  if (isKeyAccountSelection.value) return
  if (ownerInput.value !== selectedOwner.value) {
    selectedOwner.value = ''
  }
  ownerComboboxOpen.value = true
}

function selectOwner(value) {
  selectedOwner.value = value
  ownerInput.value = value
  ownerComboboxOpen.value = false
}

function clearOwner() {
  selectedOwner.value = ''
  ownerInput.value = ''
  ownerComboboxOpen.value = false
}

function handleDocumentMouseDown(event) {
  if (!regionComboboxRef.value?.contains(event.target)) {
    regionComboboxOpen.value = false
  }
  if (!ownerComboboxRef.value?.contains(event.target)) {
    ownerComboboxOpen.value = false
  }
}

function handleApply() {
  const keyAccountMode = isKeyAccountSelection.value
  const ownerKeyword = ownerInput.value.trim()
  const regionKeyword = regionInput.value.trim()
  emit('apply', {
    keyword: keyword.value,
    special_project: specialProject.value,
    industry: keyAccountMode ? '' : industry.value,
    region: keyAccountMode ? '' : selectedRegion.value,
    region_keyword: keyAccountMode ? '' : (selectedRegion.value ? '' : regionKeyword),
    owner: keyAccountMode ? '' : selectedOwner.value,
    owner_keyword: keyAccountMode ? '' : (selectedOwner.value ? '' : ownerKeyword),
    interaction_min: keyAccountMode ? null : interaction_min.value,
    interaction_period: keyAccountMode ? null : interaction_period.value,
    attribute: keyAccountMode ? '' : attribute.value,
    channel: keyAccountMode ? '' : channel.value,
  })
}

watch(specialProject, (value) => {
  if (value !== '重客') return
  regionComboboxOpen.value = false
  ownerComboboxOpen.value = false
})

onMounted(() => {
  fetchFilterOptions()
  document.addEventListener('mousedown', handleDocumentMouseDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentMouseDown)
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
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
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
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
      </div>

      <!-- 行业 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持行业筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">行业</label>
        <select
          v-model="industry"
          :disabled="isKeyAccountSelection"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none disabled:cursor-not-allowed"
        >
          <option value="">全部行业</option>
          <option v-for="item in industries" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <!-- 省份 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持省份筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">省份</label>
        <div ref="regionComboboxRef" class="relative">
          <input
            ref="regionInputRef"
            v-model="regionInput"
            :disabled="isKeyAccountSelection"
            type="text"
            placeholder="输入省份..."
            class="w-full rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 pr-10 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
            role="combobox"
            aria-label="省份"
            :aria-expanded="regionComboboxOpen"
            autocomplete="off"
            @focus="openRegionCombobox"
            @click="openRegionCombobox"
            @input="handleRegionInput"
          />
          <button
            type="button"
            class="absolute right-0 top-0 flex h-full w-9 items-center justify-center rounded-r-lg text-[var(--muted)] hover:text-[var(--text)]"
            aria-label="展开省份列表"
            tabindex="-1"
            :disabled="isKeyAccountSelection"
            @mousedown.prevent
            @click="openRegionComboboxFromArrow"
          >
            <span class="h-2 w-2 rotate-45 border-b border-r border-current"></span>
          </button>
          <div
            v-if="regionComboboxOpen && !isKeyAccountSelection"
            class="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-[100] max-h-60 overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--panel)] py-1 shadow-xl"
          >
            <button
              type="button"
              class="w-full px-3 py-2 text-left text-sm text-[var(--muted)] hover:bg-white/10"
              @mousedown.prevent="clearRegion"
            >
              全部省份
            </button>
            <button
              v-for="item in filteredRegions"
              :key="item"
              type="button"
              class="w-full px-3 py-2 text-left text-sm text-[var(--text)] hover:bg-white/10"
              @mousedown.prevent="selectRegion(item)"
            >
              {{ item }}
            </button>
            <div
              v-if="filteredRegions.length === 0"
              class="px-3 py-2 text-sm text-[var(--muted)]"
            >
              无匹配省份
            </div>
          </div>
        </div>
      </div>

      <!-- 负责人 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持负责人筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">负责人</label>
        <div ref="ownerComboboxRef" class="relative">
          <input
            ref="ownerInputRef"
            v-model="ownerInput"
            :disabled="isKeyAccountSelection"
            type="text"
            placeholder="输入负责人名称..."
            class="w-full rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 pr-10 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
            role="combobox"
            aria-label="负责人"
            :aria-expanded="ownerComboboxOpen"
            autocomplete="off"
            @focus="openOwnerCombobox"
            @click="openOwnerCombobox"
            @input="handleOwnerInput"
          />
          <button
            type="button"
            class="absolute right-0 top-0 flex h-full w-9 items-center justify-center rounded-r-lg text-[var(--muted)] hover:text-[var(--text)]"
            aria-label="展开负责人列表"
            tabindex="-1"
            :disabled="isKeyAccountSelection"
            @mousedown.prevent
            @click="openOwnerComboboxFromArrow"
          >
            <span class="h-2 w-2 rotate-45 border-b border-r border-current"></span>
          </button>
          <div
            v-if="ownerComboboxOpen && !isKeyAccountSelection"
            class="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-[100] max-h-60 overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--panel)] py-1 shadow-xl"
          >
            <button
              type="button"
              class="w-full px-3 py-2 text-left text-sm text-[var(--muted)] hover:bg-white/10"
              @mousedown.prevent="clearOwner"
            >
              全部负责人
            </button>
            <button
              v-for="item in filteredOwners"
              :key="item"
              type="button"
              class="w-full px-3 py-2 text-left text-sm text-[var(--text)] hover:bg-white/10"
              @mousedown.prevent="selectOwner(item)"
            >
              {{ item }}
            </button>
            <div
              v-if="filteredOwners.length === 0"
              class="px-3 py-2 text-sm text-[var(--muted)]"
            >
              无匹配负责人
            </div>
          </div>
        </div>
      </div>

      <!-- 互动次数筛选 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持互动次数筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">互动次数 ≥</label>
        <div class="grid grid-cols-[minmax(0,1fr)_3.5rem] gap-1">
          <select
            v-model.number="interaction_period"
            :disabled="isKeyAccountSelection"
            class="min-w-0 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-2 py-2 text-xs text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
          >
            <option v-for="p in periodOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
          <input
            v-model.number="interaction_min"
            :disabled="isKeyAccountSelection"
            type="number"
            min="0"
            placeholder="0"
            class="min-w-0 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-2 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
          />
        </div>
      </div>

      <!-- 是否为重客 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持该筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">是否为重客</label>
        <select
          v-model="attribute"
          :disabled="isKeyAccountSelection"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option value="">全部</option>
          <option value="heavy">是重客</option>
          <option value="non_heavy">不是重客</option>
        </select>
      </div>

      <!-- 互动方式 -->
      <div
        class="flex min-w-0 flex-col gap-1.5 transition-opacity"
        :class="{ 'opacity-50': isKeyAccountSelection }"
        :title="isKeyAccountSelection ? '重客列表暂不支持互动方式筛选' : ''"
      >
        <label class="text-xs font-medium text-[var(--muted)]">互动方式</label>
        <select
          v-model="channel"
          :disabled="isKeyAccountSelection"
          class="rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--brand)] focus:outline-none"
        >
          <option v-for="item in channels" :key="item.value" :value="item.value">{{ item.label }}</option>
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
