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
      <div class="list-count">共 {{ total }} 条记录</div>
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
      <button
        class="page-btn"
        :disabled="page <= 1"
        @click="onPageChange(page - 1)"
      >
        上一页
      </button>
      <span class="page-info">第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
      <button
        class="page-btn"
        :disabled="page >= totalPages"
        @click="onPageChange(page + 1)"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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

const totalPages = computed(() => Math.ceil(props.total / props.size))

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
  gap: 20px;
  padding: 24px 0;
}

.page-btn {
  padding: 10px 20px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 8px;
  color: #cdd6f4;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.page-btn:hover:not(:disabled) {
  background: #313244;
  border-color: #45475a;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: 14px;
  color: #7f849c;
}
</style>
