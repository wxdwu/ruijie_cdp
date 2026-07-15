<script setup>
import { ref, computed, onBeforeUnmount, watch } from "vue"

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => [],
  },
  options: {
    type: Array,
    default: () => [],
  },
  placeholder: {
    type: String,
    default: "请选择",
  },
  allLabel: {
    type: String,
    default: "全部",
  },
  searchable: {
    type: Boolean,
    default: false,
  },
  searchPlaceholder: {
    type: String,
    default: "搜索...",
  },
})

const emit = defineEmits(["update:modelValue", "change"])

const open = ref(false)
const search = ref("")
const wrapper = ref(null)

const filteredOptions = computed(() => {
  if (!props.searchable || !search.value.trim()) return props.options
  const kw = search.value.trim().toLowerCase()
  return props.options.filter(opt => {
    const text = String(opt.label || opt.value || "").toLowerCase()
    return text.includes(kw)
  })
})

const selectedLabels = computed(() => {
  return props.modelValue.map(v => {
    const opt = props.options.find(o => o.value === v)
    return opt?.label || v
  })
})

const isAll = computed(() => props.modelValue.length === 0)
const displayText = computed(() => {
  if (isAll.value) return props.placeholder
  if (props.modelValue.length === 1) return selectedLabels.value[0]
  return `已选 ${props.modelValue.length} 项`
})

function toggle() {
  open.value = !open.value
  if (open.value) search.value = ""
}

function close() {
  open.value = false
  search.value = ""
}

function updateValue(next) {
  emit("update:modelValue", next)
  emit("change")
}

function toggleValue(value) {
  const set = new Set(props.modelValue)
  if (set.has(value)) set.delete(value)
  else set.add(value)
  updateValue(Array.from(set))
}

function clearAll() {
  updateValue([])
}

function selectAll() {
  const all = filteredOptions.value.map(o => o.value)
  const set = new Set([...props.modelValue, ...all])
  updateValue(Array.from(set))
}

function handleClickOutside(e) {
  if (wrapper.value && !wrapper.value.contains(e.target)) close()
}

watch(open, (val) => {
  if (val) window.addEventListener("click", handleClickOutside, true)
  else window.removeEventListener("click", handleClickOutside, true)
})

onBeforeUnmount(() => {
  window.removeEventListener("click", handleClickOutside, true)
})
</script>

<template>
  <div ref="wrapper" class="relative min-w-0">
    <button
      type="button"
      @click.stop="toggle"
      class="flex w-full items-center justify-between gap-2 rounded-lg border border-[var(--line)] bg-[var(--bg1)] px-3 py-2 text-sm text-[var(--text)] transition-colors hover:border-[var(--brand)]/50 focus:border-[var(--brand)] focus:outline-none"
      :class="{ 'border-[var(--brand)]': open }"
    >
      <span class="truncate">{{ displayText }}</span>
      <span
        class="shrink-0 text-xs text-[var(--muted)] transition-transform"
        :class="{ 'rotate-180': open }"
      >▼</span>
    </button>

    <div
      v-if="open"
      class="absolute left-0 right-0 top-full z-50 mt-1.5 flex max-h-72 flex-col overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--bg1)] shadow-lg"
    >
      <!-- 搜索框 -->
      <div
        v-if="searchable"
        class="sticky top-0 border-b border-[var(--line)] bg-[var(--bg1)] p-2"
        @click.stop
      >
        <input
          v-model="search"
          type="text"
          :placeholder="searchPlaceholder"
          class="w-full rounded-md border border-[var(--line)] bg-[var(--bg)] px-2 py-1.5 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
      </div>

      <!-- 操作栏 -->
      <div class="flex items-center justify-between border-b border-[var(--line)] px-3 py-1.5">
        <button
          type="button"
          class="text-xs text-[var(--brand)] hover:underline"
          @click.stop="selectAll"
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

      <!-- 选项列表 -->
      <div class="overflow-y-auto p-1">
        <label
          class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 transition-colors hover:bg-white/5"
        >
          <input
            type="checkbox"
            :checked="isAll"
            @change="clearAll"
            class="h-4 w-4 accent-[var(--brand)]"
          />
          <span class="text-sm text-[var(--muted)]">{{ allLabel }}</span>
        </label>
        <div class="my-1 border-b border-[var(--line)]"></div>
        <label
          v-for="opt in filteredOptions"
          :key="opt.value"
          class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 transition-colors hover:bg-white/5"
        >
          <input
            type="checkbox"
            :checked="modelValue.includes(opt.value)"
            @change="toggleValue(opt.value)"
            class="h-4 w-4 accent-[var(--brand)]"
          />
          <span class="text-sm text-[var(--text)]">{{ opt.label || opt.value }}</span>
        </label>
        <div
          v-if="filteredOptions.length === 0"
          class="px-2.5 py-3 text-center text-sm text-[var(--muted)]"
        >
          无匹配结果
        </div>
      </div>
    </div>
  </div>
</template>
