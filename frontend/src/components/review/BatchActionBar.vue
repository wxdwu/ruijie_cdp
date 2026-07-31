<template>
  <div v-if="selectedIds.length > 0" class="batch-action-bar">
    <div class="batch-info">
      <span class="selected-count">已选择 {{ selectedIds.length }} 项</span>
      <button class="clear-btn" @click="onClear">清除选择</button>
    </div>
    <div class="batch-actions">
      <button class="action-btn approve" :disabled="batchBusy" @click="onBatchApprove">
        <span v-if="pendingApprove" class="btn-spinner" aria-hidden="true"></span>
        <span v-else class="btn-icon">✅</span>
        {{ pendingApprove ? '处理中…' : '批量通过' }}
      </button>
      <button class="action-btn reject" :disabled="batchBusy" @click="onBatchReject">
        <span v-if="pendingReject" class="btn-spinner" aria-hidden="true"></span>
        <span v-else class="btn-icon">❌</span>
        {{ pendingReject ? '处理中…' : '批量拒绝' }}
      </button>
      <button class="action-btn revoke" :disabled="batchBusy" @click="onBatchRevoke">
        <span v-if="pendingRevoke" class="btn-spinner" aria-hidden="true"></span>
        <span v-else class="btn-icon">↩</span>
        {{ pendingRevoke ? '处理中…' : '批量撤销审核' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
const props = defineProps<{
  selectedIds: number[]
  pendingActions?: Record<string, boolean>
}>()

// 批量操作级别：仅正在进行的批量操作按钮进入 loading，其它批量按钮禁用（防重复）
const isPending = (action: 'approve' | 'reject' | 'revoke') =>
  !!props.pendingActions?.[`batch:${action}`]
const pendingApprove = computed(() => isPending('approve'))
const pendingReject = computed(() => isPending('reject'))
const pendingRevoke = computed(() => isPending('revoke'))
const batchBusy = computed(() => pendingApprove.value || pendingReject.value || pendingRevoke.value)

const emit = defineEmits<{
  (e: 'batch-approve', ids: number[]): void
  (e: 'batch-reject', ids: number[]): void
  (e: 'batch-revoke', ids: number[]): void
  (e: 'clear'): void
}>()

const onBatchApprove = () => {
  emit('batch-approve', props.selectedIds)
}

const onBatchReject = () => {
  emit('batch-reject', props.selectedIds)
}

const onBatchRevoke = () => {
  emit('batch-revoke', props.selectedIds)
}

const onClear = () => {
  emit('clear')
}
</script>

<style scoped>
.batch-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: linear-gradient(135deg, #1e1e2e 0%, #181825 100%);
  border: 1px solid #45475a;
  border-radius: 12px;
  margin-bottom: 16px;
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.batch-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.selected-count {
  font-size: 14px;
  font-weight: 600;
  color: #cdd6f4;
}

.clear-btn {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid #585b70;
  border-radius: 6px;
  color: #9399b2;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.clear-btn:hover {
  background: #313244;
  color: #cdd6f4;
}

.batch-actions {
  display: flex;
  gap: 12px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-icon {
  font-size: 16px;
}

/* 按钮内 loading 小圈：颜色跟随按钮文字色（currentColor） */
.btn-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.action-btn.approve {
  background: linear-gradient(135deg, #a6e3a1 0%, #94e2d5 100%);
  color: #1e1e2e;
}

.action-btn.approve:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(166, 227, 161, 0.3);
}

.action-btn.reject {
  background: linear-gradient(135deg, #f38ba8 0%, #eba0ac 100%);
  color: #1e1e2e;
}

.action-btn.reject:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(243, 139, 168, 0.3);
}

/* 批量撤销审核：中性琥珀色，区别于通过(绿)/拒绝(红) */
.action-btn.revoke {
  background: linear-gradient(135deg, #f9e2af 0%, #fab387 100%);
  color: #1e1e2e;
}

.action-btn.revoke:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(249, 226, 175, 0.3);
}
</style>
