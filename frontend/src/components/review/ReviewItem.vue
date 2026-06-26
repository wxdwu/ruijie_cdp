<template>
  <div class="review-item" :class="{ selected: isSelected }">
    <!-- Checkbox -->
    <div class="item-checkbox">
      <input
        type="checkbox"
        :checked="isSelected"
        @change="onToggleSelect"
        :id="'checkbox-' + item.id"
      />
      <label :for="'checkbox-' + item.id" class="checkbox-label"></label>
    </div>

    <!-- Main Content -->
    <div class="item-content">
      <!-- 候选人比较区 -->
      <div class="candidates-compare">
        <!-- 候选 A -->
        <div class="candidate-panel">
          <div class="candidate-header">
            <span class="candidate-label a">候选 A</span>
            <span v-if="aiSuggestion === 'merge_a_to_b'" class="ai-suggestion merge-to">→ 建议合并到 B</span>
            <span v-else-if="aiSuggestion === 'keep'" class="ai-suggestion keep">
              {{ item.match_score >= 85 ? '✓ 建议合并' : '⚠ 需人工判断' }}
            </span>
          </div>

          <div class="company-name">{{ item.candidate_a_name }}</div>
          <div class="company-id">ID: {{ item.candidate_a_id || '—' }}</div>

          <!-- 公司详细信息 -->
          <div class="company-details" v-if="item.candidate_a_detail">
            <div class="detail-row" v-if="item.candidate_a_detail.industry">
              <span class="detail-label">行业</span>
              <span class="detail-value">{{ item.candidate_a_detail.industry }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.region">
              <span class="detail-label">区域</span>
              <span class="detail-value">{{ item.candidate_a_detail.region }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.owner_name">
              <span class="detail-label">负责人</span>
              <span class="detail-value">{{ item.candidate_a_detail.owner_name }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.contact_count !== null && item.candidate_a_detail.contact_count !== undefined">
              <span class="detail-label">联系人</span>
              <span class="detail-value">{{ item.candidate_a_detail.contact_count }} 人</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.interaction_count_30d !== null && item.candidate_a_detail.interaction_count_30d !== undefined">
              <span class="detail-label">近30天互动</span>
              <span class="detail-value">{{ item.candidate_a_detail.interaction_count_30d }} 次</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.interaction_count_total !== null && item.candidate_a_detail.interaction_count_total !== undefined">
              <span class="detail-label">总互动</span>
              <span class="detail-value">{{ item.candidate_a_detail.interaction_count_total }} 次</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.last_interaction_time">
              <span class="detail-label">最近互动</span>
              <span class="detail-value">{{ formatDateTime(item.candidate_a_detail.last_interaction_time) }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.intent_level">
              <span class="detail-label">意向等级</span>
              <span class="detail-value">{{ item.candidate_a_detail.intent_level }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.purchase_stage">
              <span class="detail-label">采购阶段</span>
              <span class="detail-value">{{ item.candidate_a_detail.purchase_stage }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_a_detail.active_opp_count !== null && item.candidate_a_detail.active_opp_count !== undefined">
              <span class="detail-label">在途商机</span>
              <span class="detail-value">{{ item.candidate_a_detail.active_opp_count }} 个</span>
            </div>
          </div>

          <!-- 数据来源标签 -->
          <div class="source-tags">
            <span class="source-label-text">数据表：</span>
            <span
              v-for="src in (item.sources_a || [])"
              :key="src"
              class="source-tag"
              :title="src"
            >{{ src }}</span>
            <span v-if="!item.sources_a || item.sources_a.length === 0" class="source-tag empty">未知</span>
          </div>
        </div>

        <!-- 中间连接区 -->
        <div class="compare-connector">
          <div class="connector-dot top"></div>
          <div class="connector-line"></div>
          <div class="connector-score">
            <div class="connector-score-num">{{ formatNum(item.match_score) }}</div>
            <div class="connector-score-label">相似度</div>
          </div>
          <div class="connector-line"></div>
          <div class="connector-dot bottom"></div>
        </div>

        <!-- 候选 B -->
        <div class="candidate-panel">
          <div class="candidate-header">
            <span class="candidate-label b">候选 B</span>
            <span v-if="aiSuggestion === 'merge_b_to_a'" class="ai-suggestion merge-to">→ 建议合并到 A</span>
          </div>

          <div class="company-name">{{ item.candidate_b_name }}</div>
          <div class="company-id">ID: {{ item.candidate_b_id || '—' }}</div>

          <!-- 公司详细信息 -->
          <div class="company-details" v-if="item.candidate_b_detail">
            <div class="detail-row" v-if="item.candidate_b_detail.industry">
              <span class="detail-label">行业</span>
              <span class="detail-value">{{ item.candidate_b_detail.industry }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.region">
              <span class="detail-label">区域</span>
              <span class="detail-value">{{ item.candidate_b_detail.region }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.owner_name">
              <span class="detail-label">负责人</span>
              <span class="detail-value">{{ item.candidate_b_detail.owner_name }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.contact_count !== null && item.candidate_b_detail.contact_count !== undefined">
              <span class="detail-label">联系人</span>
              <span class="detail-value">{{ item.candidate_b_detail.contact_count }} 人</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.interaction_count_30d !== null && item.candidate_b_detail.interaction_count_30d !== undefined">
              <span class="detail-label">近30天互动</span>
              <span class="detail-value">{{ item.candidate_b_detail.interaction_count_30d }} 次</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.interaction_count_total !== null && item.candidate_b_detail.interaction_count_total !== undefined">
              <span class="detail-label">总互动</span>
              <span class="detail-value">{{ item.candidate_b_detail.interaction_count_total }} 次</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.last_interaction_time">
              <span class="detail-label">最近互动</span>
              <span class="detail-value">{{ formatDateTime(item.candidate_b_detail.last_interaction_time) }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.intent_level">
              <span class="detail-label">意向等级</span>
              <span class="detail-value">{{ item.candidate_b_detail.intent_level }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.purchase_stage">
              <span class="detail-label">采购阶段</span>
              <span class="detail-value">{{ item.candidate_b_detail.purchase_stage }}</span>
            </div>
            <div class="detail-row" v-if="item.candidate_b_detail.active_opp_count !== null && item.candidate_b_detail.active_opp_count !== undefined">
              <span class="detail-label">在途商机</span>
              <span class="detail-value">{{ item.candidate_b_detail.active_opp_count }} 个</span>
            </div>
          </div>

          <!-- 数据来源标签 -->
          <div class="source-tags">
            <span class="source-label-text">数据表：</span>
            <span
              v-for="src in (item.sources_b || [])"
              :key="src"
              class="source-tag"
              :title="src"
            >{{ src }}</span>
            <span v-if="!item.sources_b || item.sources_b.length === 0" class="source-tag empty">未知</span>
          </div>
        </div>
      </div>

      <!-- 评分栏（位于候选面板下方） -->
      <div class="scores-bar">
        <div class="score-badge match" :style="{ width: clampPercent(item.match_score) + '%' }">
          <span class="score-title">匹配度</span>
          <span class="score-num">{{ formatNum(item.match_score) }}%</span>
        </div>
        <div class="score-badge rule" :style="{ width: clampPercent(item.rule_score) + '%' }">
          <span class="score-title">规则分</span>
          <span class="score-num">{{ formatNum(item.rule_score) }}%</span>
        </div>
        <div class="score-badge evidence" :style="{ width: clampPercent(item.evidence_score) + '%' }">
          <span class="score-title">证据分</span>
          <span class="score-num">{{ formatNum(item.evidence_score) }}%</span>
        </div>
        <div class="score-badge llm" :style="{ width: clampPercent(item.llm_score) + '%' }">
          <span class="score-title">LLM分</span>
          <span class="score-num">{{ formatNum(item.llm_score) }}%</span>
        </div>
      </div>

      <!-- AI 分析区 -->
      <div class="ai-analysis-section">
        <div class="ai-analysis-header">
          <span class="ai-icon">🧠</span>
          <span class="ai-title">AI 分析</span>
        </div>
        <div class="ai-analysis-body">
          <!-- AI 综合判断结论 -->
          <div class="ai-conclusion" v-if="item.match_score || item.llm_explanation">
            <p class="ai-conclusion-text">{{ buildAiConclusion() }}</p>
          </div>
          <!-- 证据摘要 -->
          <div class="ai-evidence-list">
            <div class="ai-evidence-item">
              <span class="ai-evidence-bullet">•</span>
              <span>嵌入向量相似度 <strong>{{ formatNum((item.embedding_similarity || 0) * 100) }}%</strong>——</span>名称向量余弦相似度<template v-if="(item.embedding_similarity || 0) >= 0.9">很高，名称高度相似</template><template v-else-if="(item.embedding_similarity || 0) >= 0.75">较高，名称有一定相似度</template><template v-else>中等偏低</template>
            </div>
            <div class="ai-evidence-item">
              <span class="ai-evidence-bullet">•</span>
              <span>共享联系人 <strong>{{ item.shared_contacts_count || 0 }}</strong> 个——<template v-if="(item.shared_contacts_count || 0) >= 5">两家公司共享大量联系人，业务关联度很高</template><template v-else-if="(item.shared_contacts_count || 0) >= 1">存在共享联系人，有业务关联</template><template v-else>未发现共享联系人</template></span>
            </div>
            <div class="ai-evidence-item">
              <span class="ai-evidence-bullet">•</span>
              <span>规则相似度 <strong>{{ formatNum(item.rule_score) }}%</strong>——基于编辑距离、子串包含、token 重叠等算法综合评估</span>
            </div>
            <div class="ai-evidence-item" v-if="item.llm_explanation">
              <span class="ai-evidence-bullet">•</span>
              <span>LLM 语义判断：{{ item.llm_explanation }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部行：元信息 + 操作按钮 -->
      <div class="bottom-row">
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

        <!-- 操作按钮 -->
        <div class="item-actions">
          <button
            v-if="item.status === 'pending' || item.status === 'need_review'"
            class="action-btn approve"
            @click="onApprove"
          >
            ✓ 确认合并
          </button>
          <button
            v-if="item.status === 'pending' || item.status === 'need_review'"
            class="action-btn reject"
            @click="onReject"
          >
            ✗ 保留独立
          </button>
          <span v-else class="reviewed-badge">
            {{ item.reviewed_at ? '已审核' : '—' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface CompanyDetail {
  industry?: string
  region?: string
  owner_name?: string
  contact_count?: number
  interaction_count_30d?: number
  interaction_count_total?: number
  last_interaction_time?: string
  source_tables?: string[]
  data_coverage?: Record<string, number>
  intent_level?: string
  purchase_stage?: string
  active_opp_count?: number
  is_existing_customer?: number
}

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
  // 扩展字段（从 evidence JSON 提取）
  sources_a?: string[]
  sources_b?: string[]
  shared_contacts_count?: number
  embedding_similarity?: number | null
  llm_explanation?: string
  // 公司详情（从 dws_customer_360 补充）
  candidate_a_detail?: CompanyDetail | null
  candidate_b_detail?: CompanyDetail | null
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

// AI 建议：基于匹配分给出合并方向提示
const aiSuggestion = computed(() => {
  const score = props.item.match_score || 0
  if (score >= 90) {
    // 高置信度：取信息更全的一方为保留方
    const a = props.item.candidate_a_detail
    const b = props.item.candidate_b_detail
    if (a && b) {
      const aWealth = (a.contact_count || 0) + (a.interaction_count_total || 0)
      const bWealth = (b.contact_count || 0) + (b.interaction_count_total || 0)
      if (aWealth > bWealth) return 'merge_b_to_a'
      if (bWealth > aWealth) return 'merge_a_to_b'
    }
    return 'keep'
  }
  if (score >= 70) return 'keep'
  return null
})

const onToggleSelect = () => {
  emit('select', props.item.id)
}

const onApprove = () => {
  emit('approve', props.item.id)
}

const onReject = () => {
  emit('reject', props.item.id)
}

// 构建 AI 综合分析结论文字
const buildAiConclusion = (): string => {
  const score = props.item.match_score || 0
  const embedding = (props.item.embedding_similarity || 0) * 100
  const shared = props.item.shared_contacts_count || 0
  const rule = props.item.rule_score || 0
  const evidence = props.item.evidence_score || 0
  const llmScore = props.item.llm_score || 0

  // 构建证据描述
  const evidencePieces: string[] = []
  if (embedding >= 90) evidencePieces.push('名称向量高度相似')
  else if (embedding >= 75) evidencePieces.push('名称向量较相似')
  if (shared >= 5) evidencePieces.push('共享多个联系人')
  else if (shared >= 1) evidencePieces.push('存在共享联系人')
  if (rule >= 80) evidencePieces.push('规则引擎强匹配')
  else if (rule >= 60) evidencePieces.push('规则引擎中等匹配')

  const evidenceText = evidencePieces.length > 0
    ? evidencePieces.join('、')
    : '综合评估以下证据'

  // 结论
  if (score >= 90) {
    let target = ''
    const a = props.item.candidate_a_detail
    const b = props.item.candidate_b_detail
    if (a && b) {
      const aW = (a.contact_count || 0) + (a.interaction_count_total || 0)
      const bW = (b.contact_count || 0) + (b.interaction_count_total || 0)
      target = aW >= bW ? '建议保留公司A' : '建议保留公司B'
    }
    return `AI 综合${evidenceText}，判定两者为同一家公司的把握极高（${formatNum(score)}%）。${target ? target + '，合并到信息更全的一方。' : '建议合并。'}`
  } else if (score >= 80) {
    return `AI 综合${evidenceText}，判定两者有很大可能为同一家公司（${formatNum(score)}%），建议合并，建议人工复核确认。`
  } else if (score >= 65) {
    return `AI 综合${evidenceText}，两者有一定相似度（${formatNum(score)}%），但证据不够充分，需要人工判断是否合并。`
  } else {
    return `AI 综合${evidenceText}，把握较低（${formatNum(score)}%），两者为同一家公司的可能性较小，建议谨慎判断。`
  }
}

const clampPercent = (val: number) => Math.min(100, Math.max(0, val || 0))
const formatNum = (val: number | null | undefined) => {
  if (val == null) return '0'
  return Number(val).toFixed(1)
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

const formatDateTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return '今天'
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays} 天前`
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
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
</script>

<style scoped>
.review-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 24px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 14px;
  margin-bottom: 16px;
  transition: all 0.2s ease;
}

.review-item:hover {
  border-color: #45475a;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
}

.review-item.selected {
  border-color: #89b4fa;
  background: linear-gradient(135deg, #1e1e2e 0%, #181825 100%);
}

.item-checkbox {
  flex-shrink: 0;
  padding-top: 4px;
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

/* ── 评分栏（位于候选面板下方、AI分析上方）── */
.scores-bar {
  display: flex;
  gap: 8px;
  margin: 16px 0;
  flex-wrap: wrap;
}

.score-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 120px;
  flex: 1;
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  transition: width 0.4s ease;
}

.score-badge .score-title {
  color: rgba(30, 30, 46, 0.85);
  font-size: 11px;
  text-transform: uppercase;
  white-space: nowrap;
}

.score-badge .score-num {
  color: #1e1e2e;
  font-size: 14px;
  font-weight: 700;
}

.score-badge.match { background: linear-gradient(90deg, #89b4fa, #b4befe); }
.score-badge.rule  { background: linear-gradient(90deg, #a6e3a1, #94e2d5); }
.score-badge.evidence { background: linear-gradient(90deg, #fab387, #f9e2af); }
.score-badge.llm  { background: linear-gradient(90deg, #cba6f7, #f5c2e7); }

/* ── 候选人比较区 ── */
.candidates-compare {
  display: flex;
  gap: 20px;
  align-items: stretch;
  margin-bottom: 16px;
}

.candidate-panel {
  flex: 1;
  min-width: 0;
  padding: 16px 18px;
  background: #181825;
  border-radius: 10px;
  border: 1px solid #313244;
}

.candidate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.candidate-label {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.candidate-label.a {
  background: rgba(137, 180, 250, 0.25);
  color: #89b4fa;
}

.candidate-label.b {
  background: rgba(166, 227, 161, 0.25);
  color: #a6e3a1;
}

.ai-suggestion {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.ai-suggestion.merge-to {
  color: #f9e2af;
  background: rgba(249, 226, 175, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.ai-suggestion.keep {
  color: #a6e3a1;
  background: rgba(166, 227, 161, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.company-name {
  font-size: 17px;
  font-weight: 700;
  color: #cdd6f4;
  margin-bottom: 4px;
  word-break: break-all;
}

.company-id {
  font-size: 12px;
  color: #6c7086;
  margin-bottom: 12px;
  font-family: monospace;
}

/* ── 公司详细信息 ── */
.company-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 16px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: rgba(30, 30, 46, 0.5);
  border-radius: 8px;
}

.detail-row {
  display: flex;
  gap: 6px;
  font-size: 12px;
  line-height: 1.6;
}

.detail-label {
  color: #6c7086;
  flex-shrink: 0;
  white-space: nowrap;
}

.detail-label::after {
  content: '：';
}

.detail-value {
  color: #a6adc8;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 数据来源标签 ── */
.source-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px solid rgba(49, 50, 68, 0.5);
}

.source-label-text {
  font-size: 11px;
  color: #585b70;
  margin-right: 2px;
}

.source-tag {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  cursor: default;
  background: rgba(137, 180, 250, 0.12);
  color: #89b4fa;
  border: 1px solid rgba(137, 180, 250, 0.2);
  transition: all 0.15s;
}

.source-tag:hover {
  background: rgba(137, 180, 250, 0.2);
}

.source-tag.empty {
  background: rgba(108, 112, 134, 0.15);
  color: #585b70;
  border-color: rgba(108, 112, 134, 0.2);
}

/* ── 中间连接器 ── */
.compare-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 50px;
}

.connector-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.connector-dot.top    { background: #89b4fa; }
.connector-dot.bottom { background: #a6e3a1; }

.connector-line {
  width: 2px;
  flex: 1;
  min-height: 18px;
  background: linear-gradient(to bottom, #89b4fa, #313244, #a6e3a1);
}

.connector-score {
  text-align: center;
  margin: 4px 0;
}

.connector-score-num {
  font-size: 20px;
  font-weight: 800;
  color: #f9e2af;
  line-height: 1;
}

.connector-score-label {
  font-size: 10px;
  color: #585b70;
  margin-top: 2px;
}

/* ── AI 分析区 ── */
.ai-analysis-section {
  background: linear-gradient(135deg, rgba(137, 180, 250, 0.08), rgba(203, 166, 247, 0.06));
  border: 1px solid rgba(137, 180, 250, 0.18);
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 14px;
}

.ai-analysis-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(137, 180, 250, 0.12);
}

.ai-icon {
  font-size: 16px;
}

.ai-title {
  font-size: 14px;
  font-weight: 700;
  color: #cba6f7;
  letter-spacing: 0.5px;
}

.ai-analysis-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ai-conclusion {
  padding: 10px 14px;
  background: rgba(203, 166, 247, 0.1);
  border-left: 3px solid #cba6f7;
  border-radius: 0 8px 8px 0;
}

.ai-conclusion-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #cdd6f4;
}

.ai-evidence-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ai-evidence-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #a6adc8;
}

.ai-evidence-bullet {
  color: #89b4fa;
  font-weight: 700;
  flex-shrink: 0;
  margin-top: 1px;
}

.ai-evidence-item strong {
  color: #f9e2af;
  font-weight: 700;
}

/* ── 底部行：元信息 + 操作按钮 ── */
.bottom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.created-at {
  font-size: 12px;
  color: #6c7086;
}

/* ── 操作按钮（右下角水平排列）── */
.item-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
  align-items: center;
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
}

/* ── 操作按钮 ── */
.action-btn {
  padding: 10px 22px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  min-width: 110px;
  white-space: nowrap;
}

.action-btn.approve {
  background: #a6e3a1;
  color: #1e1e2e;
}

.action-btn.approve:hover {
  background: #94e2d5;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(166, 227, 161, 0.35);
}

.action-btn.reject {
  background: #f38ba8;
  color: #1e1e2e;
}

.action-btn.reject:hover {
  background: #eba0ac;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(243, 139, 168, 0.35);
}

.reviewed-badge {
  padding: 8px 16px;
  background: #313244;
  border-radius: 6px;
  font-size: 12px;
  color: #7f849c;
  text-align: center;
}

/* ── 浅色主题覆盖 ── */
html[data-theme="light"] .review-item {
  background: #ffffff;
  border-color: #d8dee9;
  box-shadow: 0 2px 12px rgba(21, 45, 83, 0.06);
}

html[data-theme="light"] .review-item:hover {
  border-color: #b0bec5;
  box-shadow: 0 4px 16px rgba(21, 45, 83, 0.1);
}

html[data-theme="light"] .review-item.selected {
  border-color: #5a9fd4;
  background: linear-gradient(135deg, #f0f6fd 0%, #e8f0fb 100%);
}

html[data-theme="light"] .candidate-panel {
  background: #f9fafc;
  border-color: #d8dee9;
}

html[data-theme="light"] .candidate-label.a {
  background: rgba(47, 127, 232, 0.12);
  color: #2f7fe8;
}

html[data-theme="light"] .candidate-label.b {
  background: rgba(21, 150, 105, 0.12);
  color: #159669;
}

html[data-theme="light"] .company-name {
  color: #122033;
}

html[data-theme="light"] .company-id {
  color: #607084;
}

html[data-theme="light"] .company-details {
  background: rgba(47, 127, 232, 0.04);
}

html[data-theme="light"] .detail-label {
  color: #607084;
}

html[data-theme="light"] .detail-value {
  color: #3b4a5e;
}

html[data-theme="light"] .source-tags {
  border-top-color: #d8dee9;
}

html[data-theme="light"] .source-label-text {
  color: #8a96a8;
}

html[data-theme="light"] .source-tag {
  background: rgba(47, 127, 232, 0.08);
  color: #2f7fe8;
  border-color: rgba(47, 127, 232, 0.2);
}

html[data-theme="light"] .source-tag.empty {
  background: rgba(96, 112, 132, 0.08);
  color: #8a96a8;
  border-color: rgba(96, 112, 132, 0.15);
}

html[data-theme="light"] .connector-dot.top {
  background: #5a9fd4;
}

html[data-theme="light"] .connector-dot.bottom {
  background: #159669;
}

html[data-theme="light"] .connector-line {
  background: linear-gradient(to bottom, #5a9fd4, #d8dee9, #159669);
}

html[data-theme="light"] .connector-score-num {
  color: #8b6914;
}

html[data-theme="light"] .connector-score-label {
  color: #8a96a8;
}

/* AI 分析区 - 浅色 */
html[data-theme="light"] .ai-analysis-section {
  background: linear-gradient(135deg, rgba(47, 127, 232, 0.04), rgba(124, 77, 196, 0.03));
  border-color: rgba(47, 127, 232, 0.15);
}

html[data-theme="light"] .ai-analysis-header {
  border-bottom-color: rgba(47, 127, 232, 0.1);
}

html[data-theme="light"] .ai-title {
  color: #6b3fa0;
}

html[data-theme="light"] .ai-conclusion {
  background: rgba(124, 77, 196, 0.06);
  border-left-color: #7c4dc4;
}

html[data-theme="light"] .ai-conclusion-text {
  color: #3b4a5e;
}

html[data-theme="light"] .ai-evidence-item {
  color: #4a5568;
}

html[data-theme="light"] .ai-evidence-bullet {
  color: #2f7fe8;
}

html[data-theme="light"] .ai-evidence-item strong {
  color: #8b6914;
}

/* 评分栏 - 浅色 */
html[data-theme="light"] .score-badge {
  background: rgba(96, 112, 132, 0.08);
}

html[data-theme="light"] .score-title {
  color: #607084;
}

html[data-theme="light"] .score-num {
  color: #3b4a5e;
}

html[data-theme="light"] .score-badge.match {
  background: rgba(47, 127, 232, 0.12);
}
html[data-theme="light"] .score-badge.rule {
  background: rgba(21, 150, 105, 0.12);
}
html[data-theme="light"] .score-badge.evidence {
  background: rgba(138, 105, 20, 0.12);
}
html[data-theme="light"] .score-badge.llm {
  background: rgba(124, 77, 196, 0.12);
}

/* 类型和状态标签 - 浅色 */
html[data-theme="light"] .review-type.company_merge {
  background: rgba(47, 127, 232, 0.1);
  color: #2f7fe8;
}

html[data-theme="light"] .review-type.contact_merge {
  background: rgba(21, 150, 105, 0.1);
  color: #159669;
}

html[data-theme="light"] .review-type.data_quality {
  background: rgba(229, 131, 68, 0.1);
  color: #d47830;
}

html[data-theme="light"] .status-badge.pending {
  background: rgba(184, 108, 132, 0.1);
  color: #cf496d;
}

html[data-theme="light"] .status-badge.auto_merged {
  background: rgba(21, 150, 105, 0.1);
  color: #159669;
}

html[data-theme="light"] .status-badge.rejected {
  background: rgba(207, 73, 109, 0.1);
  color: #cf496d;
}

html[data-theme="light"] .status-badge.need_review {
  background: rgba(229, 131, 68, 0.1);
  color: #d47830;
}

/* 操作按钮 - 浅色保持可辨识 */
html[data-theme="light"] .action-btn.approve {
  background: #159669;
  color: #ffffff;
}

html[data-theme="light"] .action-btn.approve:hover {
  background: #108056;
}

html[data-theme="light"] .action-btn.reject {
  background: #cf496d;
  color: #ffffff;
}

html[data-theme="light"] .action-btn.reject:hover {
  background: #b83c5c;
}

html[data-theme="light"] .reviewed-badge {
  background: #e8edf3;
  color: #607084;
}

html[data-theme="light"] .created-at {
  color: #8a96a8;
}

/* 复选框标签 - 浅色 */
html[data-theme="light"] .item-select {
  color: #3b4a5e;
}

html[data-theme="light"] .ai-suggestion.merge-to {
  color: #8b6914;
  background: rgba(138, 105, 20, 0.1);
}

html[data-theme="light"] .ai-suggestion.keep {
  color: #108056;
  background: rgba(21, 150, 105, 0.1);
}
</style>
