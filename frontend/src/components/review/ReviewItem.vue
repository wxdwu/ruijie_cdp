<template>
  <div class="review-item" :class="{ selected: isSelected }">
    <div class="item-checkbox">
      <input
        type="checkbox"
        :checked="isSelected"
        @change="onToggleSelect"
        :id="'checkbox-' + item.id"
      />
      <label :for="'checkbox-' + item.id" class="checkbox-label"></label>
    </div>

    <div class="item-content">
      <div class="candidates-row">
        <div class="candidate-card">
          <div class="candidate-label">候选 A</div>
          <div class="candidate-name">{{ item.candidate_a_name }}</div>
          <div class="candidate-id">{{ item.candidate_a_id }}</div>
        </div>
        <div class="merge-arrow">
          <span class="arrow-icon">🔗</span>
        </div>
        <div class="candidate-card">
          <div class="candidate-label">候选 B</div>
          <div class="candidate-name">{{ item.candidate_b_name }}</div>
          <div class="candidate-id">{{ item.candidate_b_id }}</div>
        </div>
      </div>

      <div class="scores-row">
        <div class="score-item">
          <div class="score-label">匹配度</div>
          <div class="score-value match" :style="{ width: item.match_score + '%' }">
            {{ item.match_score }}%
          </div>
        </div>
        <div class="score-item">
          <div class="score-label">规则分</div>
          <div class="score-value rule" :style="{ width: item.rule_score + '%' }">
            {{ item.rule_score }}%
          </div>
        </div>
        <div class="score-item">
          <div class="score-label">证据分</div>
          <div class="score-value evidence" :style="{ width: item.evidence_score + '%' }">
            {{ item.evidence_score }}%
          </div>
        </div>
        <div class="score-item">
          <div class="score-label">LLM分</div>
          <div class="score-value llm" :style="{ width: item.llm_score + '%' }">
            {{ item.llm_score }}%
          </div>
        </div>
      </div>

      <div class="meta-row">
        <span class="review-type" :class="item.review_type">
          {{ getTypeLabel(item.review_type) }}
        </span>
        <span class="status-badge" :class="item.status">
          {{ getStatusLabel(item.status) }}
        </span>
        <span class="created-at">
          创建于 {{ formatDate(item.created_at) }}
        </span>
      </div>
    </div>

    <div class="item-actions">
      <button
        v-if="item.status === 'pending' || item.status === 'need_review'"
        class="action-btn approve"
        @click="onApprove"
      >
        通过
      </button>
      <button
        v-if="item.status === 'pending' || item.status === 'need_review'"
        class="action-btn reject"
        @click="onReject"
      >
        拒绝
      </button>
      <span v-else class="reviewed-badge">
        {{ item.reviewed_at ? '已审核' : '-' }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface ReviewItemData {
  id: number
  review_type: string
  candidate_a_id: string
  candidate_a_name: string
  candidate_b_id: string
  candidate_b_name: string
  match_score: number
  rule_score: number
  evidence_score: number
  llm_score: number
  status: string
  created_at: string
  reviewed_at?: string
  reviewed_by?: string
}

const props = defineProps<{
  item: ReviewItemData
  selected: boolean
}>()

const emit = defineEmits<{
  (e: 'select', id: number): void
  (e: 'approve', id: number): void
  (e: 'reject', id: number): void
}>()

const isSelected = computed(() => props.selected)

const onToggleSelect = () => {
  emit('select', props.item.id)
}

const onApprove = () => {
  emit('approve', props.item.id)
}

const onReject = () => {
  emit('reject', props.item.id)
}

const getTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    company_merge: '公司合并',
    contact_merge: '联系人合并',
    data_quality: '数据质量',
  }
  return labels[type] || type
}

const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    pending: '待审核',
    auto_merged: '自动合并',
    rejected: '已拒绝',
    need_review: '需人工审核',
  }
  return labels[status] || status
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.review-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 12px;
  margin-bottom: 12px;
  transition: all 0.2s ease;
}

.review-item:hover {
  border-color: #45475a;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.review-item.selected {
  border-color: #89b4fa;
  background: linear-gradient(135deg, #1e1e2e 0%, #181825 100%);
}

.item-checkbox {
  flex-shrink: 0;
}

.item-checkbox input[type='checkbox'] {
  width: 20px;
  height: 20px;
  cursor: pointer;
  accent-color: #89b4fa;
}

.checkbox-label {
  display: none;
}

.item-content {
  flex: 1;
  min-width: 0;
}

.candidates-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.candidate-card {
  flex: 1;
  padding: 12px 16px;
  background: #181825;
  border-radius: 8px;
  border: 1px solid #313244;
}

.candidate-label {
  font-size: 11px;
  color: #6c7086;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.candidate-name {
  font-size: 16px;
  font-weight: 600;
  color: #cdd6f4;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.candidate-id {
  font-size: 12px;
  color: #7f849c;
}

.merge-arrow {
  flex-shrink: 0;
  padding: 8px;
}

.arrow-icon {
  font-size: 24px;
}

.scores-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.score-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.score-label {
  font-size: 11px;
  color: #7f849c;
}

.score-value {
  height: 24px;
  line-height: 24px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #1e1e2e;
  text-align: right;
  min-width: 60px;
  transition: width 0.3s ease;
}

.score-value.match {
  background: linear-gradient(90deg, #89b4fa, #b4befe);
}

.score-value.rule {
  background: linear-gradient(90deg, #a6e3a1, #94e2d5);
}

.score-value.evidence {
  background: linear-gradient(90deg, #fab387, #f9e2af);
}

.score-value.llm {
  background: linear-gradient(90deg, #cba6f7, #f5c2e7);
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.review-type,
.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

.review-type.company_merge {
  background: rgba(137, 180, 250, 0.2);
  color: #89b4fa;
}

.review-type.contact_merge {
  background: rgba(166, 227, 161, 0.2);
  color: #a6e3a1;
}

.review-type.data_quality {
  background: rgba(250, 179, 135, 0.2);
  color: #fab387;
}

.status-badge.pending {
  background: rgba(245, 194, 231, 0.2);
  color: #f5c2e7;
}

.status-badge.auto_merged {
  background: rgba(166, 227, 161, 0.2);
  color: #a6e3a1;
}

.status-badge.rejected {
  background: rgba(243, 139, 168, 0.2);
  color: #f38ba8;
}

.status-badge.need_review {
  background: rgba(250, 179, 135, 0.2);
  color: #fab387;
}

.created-at {
  font-size: 12px;
  color: #6c7086;
  margin-left: auto;
}

.item-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.action-btn {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  min-width: 80px;
}

.action-btn.approve {
  background: #a6e3a1;
  color: #1e1e2e;
}

.action-btn.approve:hover {
  background: #94e2d5;
  transform: translateY(-1px);
}

.action-btn.reject {
  background: #f38ba8;
  color: #1e1e2e;
}

.action-btn.reject:hover {
  background: #eba0ac;
  transform: translateY(-1px);
}

.reviewed-badge {
  padding: 8px 16px;
  background: #313244;
  border-radius: 6px;
  font-size: 12px;
  color: #7f849c;
  text-align: center;
}
</style>
