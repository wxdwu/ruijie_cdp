<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { customerApi } from '../../api'

const emit = defineEmits(['apply'])

const keyword = ref('')
const industry = ref('')
const ownerInput = ref('')
const selectedOwner = ref('')
const ownerComboboxOpen = ref(false)
const ownerComboboxRef = ref(null)
const ownerInputRef = ref(null)
const specialProject = ref(null)
const channel = ref('')
const interaction_min = ref(null)

const industries = ref([])
const owners = ref([])
const loading = ref(false)

const channels = [
  { value: '', label: '全部' },
  { value: 'email', label: '邮件' },
  { value: 'web', label: '官网' },
  { value: 'event', label: '直播/活动' },
  { value: 'wechat', label: '微信' },
]

const filteredOwners = computed(() => {
  const q = ownerInput.value.trim().toLowerCase()
  if (!q) return owners.value
  return owners.value.filter((item) => item.toLowerCase().includes(q))
})

async function fetchFilterOptions() {
  try {
    const res = await customerApi.filterOptions()
    industries.value = res.industries || []
    owners.value = res.owners || []
  } catch (e) {
    console.error('Failed to fetch filter options:', e)
  }
}

function openOwnerCombobox() {
  ownerComboboxOpen.value = true
}

function openOwnerComboboxFromArrow() {
  ownerComboboxOpen.value = true
  ownerInputRef.value?.focus()
}

function handleOwnerInput() {
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
  if (!ownerComboboxRef.value?.contains(event.target)) {
    ownerComboboxOpen.value = false
  }
}

function handleApply() {
  const ownerKeyword = ownerInput.value.trim()
  emit('apply', {
    keyword: keyword.value,
    industry: industry.value,
    owner: selectedOwner.value,
    owner_keyword: selectedOwner.value ? '' : ownerKeyword,
    interaction_min: interaction_min.value,
    channel: channel.value,
  })
}

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
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <!-- 专项 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">专项</label>
        <select disabled
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
        <div ref="ownerComboboxRef" class="relative">
          <input
            ref="ownerInputRef"
            v-model="ownerInput"
            type="text"
            placeholder="输入负责人名称..."
            class="w-full rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 pr-16 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
            role="combobox"
            aria-label="负责人"
            :aria-expanded="ownerComboboxOpen"
            autocomplete="off"
            @focus="openOwnerCombobox"
            @click="openOwnerCombobox"
            @input="handleOwnerInput"
          />
          <button
            v-if="ownerInput"
            type="button"
            class="absolute right-8 top-1/2 -translate-y-1/2 text-sm text-[var(--muted)] hover:text-[var(--text)]"
            aria-label="清空负责人"
            @click="clearOwner"
          >
            x
          </button>
          <button
            type="button"
            class="absolute right-0 top-0 flex h-full w-9 items-center justify-center rounded-r-lg text-[var(--muted)] hover:text-[var(--text)]"
            aria-label="展开负责人列表"
            tabindex="-1"
            @mousedown.prevent
            @click="openOwnerComboboxFromArrow"
          >
            <span class="h-2 w-2 rotate-45 border-b border-r border-current"></span>
          </button>
          <div
            v-if="ownerComboboxOpen"
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

      <!-- 近30天互动 -->
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-medium text-[var(--muted)]">近30天互动 ≥</label>
        <input
          v-model.number="interaction_min"
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
          v-model="channel"
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
