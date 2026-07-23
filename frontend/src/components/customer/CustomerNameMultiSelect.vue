<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import { customerApi } from "../../api"

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => [],
  },
  specialProject: {
    type: Array,
    default: () => [],
  },
  placeholder: {
    type: String,
    default: "全部客户",
  },
  allLabel: {
    type: String,
    default: "全部客户",
  },
  searchPlaceholder: {
    type: String,
    default: "搜索客户...",
  },
})

const emit = defineEmits(["update:modelValue", "change"])

const open = ref(false)
const search = ref("")
const options = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const error = ref("")
const hasMore = ref(false)
const wrapper = ref(null)
const searchInput = ref(null)
const optionList = ref(null)

const SEARCH_DELAY = 300
const PAGE_SIZE = 50
let searchTimer = null
let searchRequestId = 0
let searchAbortController = null
let ignoreNextSearchChange = false

const isAll = computed(() => props.modelValue.length === 0)
const visibleValues = computed(() => {
  return Array.from(new Set([...props.modelValue, ...options.value]))
})
const canSelectAllCurrent = computed(() => (
  options.value.length > 0 && !loading.value && !loadingMore.value
))
const displayText = computed(() => {
  if (isAll.value) return props.placeholder
  if (props.modelValue.length === 1) return props.modelValue[0]
  return `已选 ${props.modelValue.length} 项`
})

function cancelSearch() {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
    searchTimer = null
  }
  searchAbortController?.abort()
  searchAbortController = null
  searchRequestId += 1
  loading.value = false
  loadingMore.value = false
}

async function fetchOptions({ reset = false } = {}) {
  const query = search.value.trim()
  if (!reset && (!hasMore.value || loading.value || loadingMore.value)) return

  const requestId = ++searchRequestId
  searchAbortController?.abort()
  const abortController = new AbortController()
  searchAbortController = abortController
  const offset = reset ? 0 : options.value.length
  if (reset) {
    options.value = []
    hasMore.value = false
    loading.value = true
  } else {
    loadingMore.value = true
  }
  error.value = ""

  try {
    const result = await customerApi.nameOptions({
      q: query || undefined,
      special_project: props.specialProject,
      offset,
      limit: PAGE_SIZE,
    }, { signal: abortController.signal })
    if (requestId !== searchRequestId || abortController.signal.aborted) return
    const incoming = (result.items || []).slice(0, PAGE_SIZE)
    options.value = reset
      ? incoming
      : Array.from(new Set([...options.value, ...incoming]))
    hasMore.value = Boolean(result.has_more)
  } catch (requestError) {
    if (requestId !== searchRequestId || abortController.signal.aborted) return
    console.error("Failed to fetch customer-name options:", requestError)
    if (reset) options.value = []
    error.value = "加载失败，请重试"
  } finally {
    if (requestId === searchRequestId) {
      searchAbortController = null
      loading.value = false
      loadingMore.value = false
    }
  }
}

function scheduleSearch() {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchAbortController?.abort()
  searchAbortController = null
  searchRequestId += 1
  loading.value = false
  loadingMore.value = false
  options.value = []
  hasMore.value = false
  error.value = ""
  if (!open.value) return
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    fetchOptions({ reset: true })
  }, SEARCH_DELAY)
}

function searchNow() {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer)
    searchTimer = null
  }
  fetchOptions({ reset: true })
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    fetchOptions({ reset: true })
    nextTick(() => searchInput.value?.focus())
  } else {
    close()
  }
}

function close() {
  open.value = false
  search.value = ""
  options.value = []
  hasMore.value = false
  error.value = ""
  cancelSearch()
}

function updateValue(next) {
  emit("update:modelValue", next)
  emit("change")
}

function toggleValue(value) {
  const next = new Set(props.modelValue)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  updateValue(Array.from(next))
}

function clearAll() {
  if (!props.modelValue.length) return
  updateValue([])
}

function selectAllCurrent() {
  if (!canSelectAllCurrent.value) return
  const next = Array.from(new Set([...props.modelValue, ...options.value]))
  if (next.length === props.modelValue.length) return
  updateValue(next)
}

function retryLoad() {
  fetchOptions({ reset: options.value.length === 0 })
}

function handleOptionsScroll(event) {
  const element = event.currentTarget
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 40) {
    fetchOptions()
  }
}

function handleClickOutside(event) {
  if (wrapper.value && !wrapper.value.contains(event.target)) close()
}

watch(search, () => {
  if (ignoreNextSearchChange) {
    ignoreNextSearchChange = false
    return
  }
  scheduleSearch()
})
watch(() => props.specialProject, () => {
  if (search.value) ignoreNextSearchChange = true
  search.value = ""
  options.value = []
  hasMore.value = false
  error.value = ""
  cancelSearch()
  if (open.value) nextTick(() => fetchOptions({ reset: true }))
}, { deep: true })

watch(open, value => {
  if (value) window.addEventListener("click", handleClickOutside, true)
  else window.removeEventListener("click", handleClickOutside, true)
})

onBeforeUnmount(() => {
  cancelSearch()
  window.removeEventListener("click", handleClickOutside, true)
})
</script>

<template>
  <div ref="wrapper" class="relative min-w-0">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] transition-colors hover:border-[var(--brand)]/50 focus:border-[var(--brand)] focus:outline-none"
      :class="{ 'border-[var(--brand)]': open }"
      @click.stop="toggle"
    >
      <span class="truncate">{{ displayText }}</span>
      <span
        class="shrink-0 text-xs text-[var(--muted)] transition-transform"
        :class="{ 'rotate-180': open }"
      >▼</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 right-0 top-full z-50 mt-1.5 flex max-h-72 min-w-64 flex-col overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--bg1)] shadow-lg"
      @click.stop
    >
      <div class="border-b border-[var(--line)] p-2">
        <input
          ref="searchInput"
          v-model="search"
          type="search"
          :placeholder="searchPlaceholder"
          class="w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-2 py-1.5 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
          @keyup.enter.prevent="searchNow"
        />
      </div>

      <div class="flex items-center justify-between border-b border-[var(--line)] px-3 py-1.5">
        <button
          type="button"
          class="text-xs text-[var(--brand)] hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:no-underline"
          :disabled="!canSelectAllCurrent"
          @click.stop="selectAllCurrent"
        >
          全选
        </button>
        <button
          type="button"
          class="text-xs text-[var(--muted)] hover:text-[var(--text)] hover:underline"
          @click.stop="clearAll"
        >
          清空
        </button>
      </div>

      <div
        ref="optionList"
        data-testid="customer-name-option-list"
        tabindex="0"
        class="min-h-0 flex-1 overflow-y-auto p-1"
        @scroll="handleOptionsScroll"
      >
        <label class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 transition-colors hover:bg-white/5">
          <input
            type="checkbox"
            :checked="isAll"
            class="h-4 w-4 accent-[var(--brand)]"
            @click.prevent="clearAll"
          />
          <span class="text-sm text-[var(--muted)]">{{ allLabel }}</span>
        </label>
        <div class="my-1 border-b border-[var(--line)]"></div>

        <div v-if="loading && !visibleValues.length" class="px-2.5 py-3 text-center text-sm text-[var(--muted)]">
          客户名称加载中...
        </div>
        <div v-else-if="error && !visibleValues.length" class="px-2.5 py-3 text-center text-sm text-[var(--muted)]">
          <div>{{ error }}</div>
          <button type="button" class="mt-1 text-[var(--brand)] hover:underline" @click="retryLoad">
            重试
          </button>
        </div>
        <template v-else-if="visibleValues.length">
          <label
            v-for="value in visibleValues"
            :key="value"
            class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 transition-colors hover:bg-white/5"
            :title="value"
          >
            <input
              type="checkbox"
              :checked="modelValue.includes(value)"
              class="h-4 w-4 accent-[var(--brand)]"
              @change="toggleValue(value)"
            />
            <span class="truncate text-sm text-[var(--text)]">{{ value }}</span>
          </label>
          <div v-if="loadingMore || loading" class="px-2.5 py-2 text-center text-xs text-[var(--muted)]">
            更多客户加载中...
          </div>
          <div v-else-if="error" class="px-2.5 py-2 text-center text-xs text-[var(--muted)]">
            {{ error }}
            <button type="button" class="ml-1 text-[var(--brand)] hover:underline" @click="retryLoad">
              重试
            </button>
          </div>
          <div v-else-if="hasMore" class="px-2.5 py-2 text-center text-xs text-[var(--muted)]">
            向下滚动加载更多
          </div>
        </template>
        <div v-else class="px-2.5 py-3 text-center text-sm text-[var(--muted)]">
          无匹配结果
        </div>
      </div>
    </div>
  </div>
</template>
