<template>
  <div class="review-list">
    <div class="list-header">
      <div class="select-all">
        <input
          type="checkbox"
          :checked="isAllSelected"
          @change="onToggleSelectAll"
          id="select-all"
        />
        <label for="select-all">全选</label>
      </div>
      <div class="list-count">第 {{ page }}/{{ totalPages }} 页，共 {{ total }} 条记录</div>
    </div>

    <div class="list-content">
      <ReviewItem
        v-for="item in items"
        :key="item.id"
        :item="item"
        :selected="selectedIds.includes(item.id)"
        @select="onToggleSelect"
        @approve="onApprove"
        @reject="onReject"
      />

      <div v-if="items.length === 0" class="empty-state">
        <div class="empty-icon">📭</div>
        <div class="empty-text">暂无数据</div>
      </div>
    </div>

    <div v-if="total > size" class="pagination">
      <!-- 上一页 -->
      <button class="page-btn" :disabled="page <= 1" @click="onPageChange(page - 1)">
        « 上一页
      </button>

      <!-- 页码按钮 -->
      <button
        v-for="p in visiblePages"
        :key="p"
        class="page-btn page-num"
        :class="{ active: p === page }"
        :disabled="p === '...'"
        @click="typeof p === 'number' && onPageChange(p)"
      >
        {{ p }}
      </button>

      <!-- 下一页 -->
      <button class="page-btn" :disabled="page >= totalPages" @click="onPageChange(page + 1)">
        下一页 »
      </button>

      <!-- 跳转到指定页 -->
      <span class="page-jump">
        <span>跳至</span>
        <input
          ref="jumpInputRef"
          class="jump-input"
          type="number"
          :min="1"
          :max="totalPages"
          @keyup.enter="doJump"
        />
        <span>页</span>
        <button class="page-btn jump-btn" @click="doJump">GO</button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ReviewItem, { type ReviewItemData } from './ReviewItem.vue'

const props = defineProps<{
  items: ReviewItemData[]
  total: number
  page: number
  size: number
  selectedIds: number[]
}>()

const emit = defineEmits<{
  (e: 'select', id: number): void
  (e: 'select-all', selected: boolean): void
  (e: 'approve', id: number): void
  (e: 'reject', id: number): void
  (e: 'page-change', page: number): void
}>()

const jumpInputRef = ref<HTMLInputElement | null>(null)

const totalPages = computed(() => Math.ceil(props.total / props.size))

/** 生成可见页码数组，当前页前后各2页，首尾必显 */
const visiblePages = computed(() => {
  const current = props.page
  const total = totalPages.value
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }
  const pages: (number | string)[] = []
  pages.push(1)
  let start = Math.max(2, current - 2)
  let end = Math.min(total - 1, current + 2)
  if (current <= 4) {
    end = Math.min(total - 1, 6)
  }
  if (current >= total - 3) {
    start = Math.max(2, total - 5)
  }
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  pages.push(total)
  return pages
})

const isAllSelected = computed(() => {
  if (props.items.length === 0) return false
  return props.items.every((item) => props.selectedIds.includes(item.id))
})

const onToggleSelect = (id: number) => {
  emit('select', id)
}

const onToggleSelectAll = () => {
  emit('select-all', !isAllSelected.value)
}

const onApprove = (id: number) => {
  emit('approve', id)
}

const onReject = (id: number) => {
  emit('reject', id)
}

const onPageChange = (newPage: number) => {
  emit('page-change', newPage)
}

const doJump = () => {
  const el = jumpInputRef.value
  if (!el) return
  const target = parseInt(el.value, 10)
  if (target >= 1 && target <= totalPages.value) {
    emit('page-change', target)
    el.value = ''
  }
}
</script>

<style scoped>
.review-list {
  background: transparent;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 12px;
  margin-bottom: 12px;
}

.select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.select-all input[type='checkbox'] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: #89b4fa;
}

.select-all label {
  font-size: 14px;
  color: #cdd6f4;
  cursor: pointer;
}

.list-count {
  font-size: 13px;
  color: #7f849c;
}

.list-content {
  min-height: 200px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 12px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 16px;
  color: #7f849c;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
  flex-wrap: wrap;
}

.page-btn {
  padding: 8px 14px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 8px;
  color: #cdd6f4;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.page-btn:hover:not(:disabled) {
  background: #313244;
  border-color: #45475a;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-num {
  min-width: 38px;
  text-align: center;
  padding: 8px 10px;
}

.page-num.active {
  background: #89b4fa;
  border-color: #89b4fa;
  color: #1e1e2e;
  font-weight: 600;
}

.page-jump {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 12px;
  font-size: 13px;
  color: #7f849c;
}

.jump-input {
  width: 52px;
  height: 34px;
  padding: 4px 6px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 6px;
  color: #cdd6f4;
  font-size: 13px;
  text-align: center;
  outline: none;
  transition: border-color 0.2s;
}

.jump-input:focus {
  border-color: #89b4fa;
}

/* 隐藏 number input 的 spinner */
.jump-input::-webkit-inner-spin-button,
.jump-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.jump-btn {
  padding: 8px 12px;
}

/* ── 浅色主题覆盖 ── */
html[data-theme="light"] .list-header {
  background: #ffffff;
  border-color: #d8dee9;
}

html[data-theme="light"] .select-all label {
  color: #3b4a5e;
}

html[data-theme="light"] .list-count {
  color: #607084;
}

html[data-theme="light"] .empty-state {
  background: #ffffff;
  border-color: #d8dee9;
}

html[data-theme="light"] .empty-text {
  color: #607084;
}

html[data-theme="light"] .page-btn {
  background: #ffffff;
  border-color: #d8dee9;
  color: #3b4a5e;
}

html[data-theme="light"] .page-btn:hover:not(:disabled) {
  background: #e8edf3;
  border-color: #b0bec5;
}

html[data-theme="light"] .page-num.active {
  background: #2f7fe8;
  border-color: #2f7fe8;
  color: #ffffff;
}

html[data-theme="light"] .page-jump {
  color: #607084;
}

html[data-theme="light"] .jump-input {
  background: #ffffff;
  border-color: #d8dee9;
  color: #3b4a5e;
}

html[data-theme="light"] .jump-input:focus {
  border-color: #2f7fe8;
}
</style>
