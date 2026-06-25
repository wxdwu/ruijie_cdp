<template>
  <div class="review-queue">
    <div class="page-header">
      <h1 class="page-title">去重审核队列</h1>
      <p class="page-subtitle">管理公司名称、联系人等数据的去重审核工作</p>
    </div>

    <div class="dedup-section">
      <button class="dedup-btn" @click="runDedup" :disabled="dedupRunning">
        <span v-if="dedupRunning" class="spinner"></span>
        {{ dedupRunning ? '去重进行中...' : '运行去重分析' }}
      </button>

      <div v-if="dedupRunning || dedupResults" class="dedup-progress">
        <div class="progress-bar-container">
          <div class="progress-bar" :style="{ width: dedupProgress + '%' }"></div>
        </div>
        <div class="progress-text">
          {{ dedupStep }}
          <span class="progress-percent">{{ formatPercent(dedupProgress) }}</span>
          <span v-if="dedupDetails && dedupDetails.completed > 0 && dedupDetails.total > 0">
            ({{ dedupDetails.completed }}/{{ dedupDetails.total }})
          </span>
        </div>
        <div v-if="dedupDetails && dedupDetails.message" class="progress-details">
          {{ dedupDetails.message }}
        </div>
        <div v-if="dedupRunning" class="progress-timer">
          耗时: {{ formatTime(elapsedTime) }}
        </div>
      </div>

      <div v-if="dedupResults && dedupStatus === 'completed'" class="dedup-results">
        <div class="result-card">
          <div class="result-number">{{ dedupResults.new_pairs_found || 0 }}</div>
          <div class="result-label">发现新重复对</div>
        </div>
        <div class="result-card">
          <div class="result-number">{{ dedupResults.auto_merged || 0 }}</div>
          <div class="result-label">自动合并</div>
        </div>
        <div class="result-card">
          <div class="result-number">{{ dedupResults.need_review || 0 }}</div>
          <div class="result-label">需人工审核</div>
        </div>
      </div>
    </div>

    <ReviewStats ref="statsRef" />

    <div class="filter-section">
      <div class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="tab-btn"
          :class="{ active: activeTab === tab.value }"
          @click="onTabChange(tab.value)"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="type-filter">
        <label class="filter-label">审核类型：</label>
        <select class="filter-select" v-model="reviewType" @change="onFilterChange">
          <option value="">全部</option>
          <option value="company_merge">公司合并</option>
          <option value="contact_merge">联系人合并</option>
          <option value="data_quality">数据质量</option>
        </select>
      </div>
    </div>

    <BatchActionBar
      :selected-ids="selectedIds"
      @batch-approve="onBatchApprove"
      @batch-reject="onBatchReject"
      @clear="onClearSelection"
    />

    <ReviewList
      :items="items"
      :total="total"
      :page="page"
      :size="size"
      :selected-ids="selectedIds"
      @select="onToggleSelect"
      @select-all="onToggleSelectAll"
      @approve="onApprove"
      @reject="onReject"
      @page-change="onPageChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import ReviewStats from '../components/review/ReviewStats.vue'
import BatchActionBar from '../components/review/BatchActionBar.vue'
import ReviewList from '../components/review/ReviewList.vue'
import type { ReviewItemData } from '../components/review/ReviewItem.vue'

const statsRef = ref<InstanceType<typeof ReviewStats> | null>(null)

const tabs = [
  { label: '全部', value: '' },
  { label: '待审核', value: 'pending' },
  { label: '自动合并', value: 'auto_merged' },
  { label: '已拒绝', value: 'rejected' },
  { label: '需人工审核', value: 'need_review' },
]

const activeTab = ref('')
const reviewType = ref('')
const page = ref(1)
const size = ref(20)
const total = ref(0)
const items = ref<ReviewItemData[]>([])
const selectedIds = ref<number[]>([])

// Deduplication state
const dedupRunning = ref(false)
const dedupProgress = ref(0)
const dedupStep = ref('')
const dedupStatus = ref('idle')
const dedupResults = ref<Record<string, number> | null>(null)
const dedupDetails = ref<{step_name: string, completed: number, total: number, message: string} | null>(null)
let dedupPollTimer: number | null = null

// Timer state (based on backend started_at, survives page refresh)
const elapsedTime = ref(0)
const dedupStartedAt = ref<string | null>(null)
let timerInterval: number | null = null

const startTimer = () => {
  updateElapsedTime()
  if (timerInterval) {
    clearInterval(timerInterval)
  }
  timerInterval = window.setInterval(updateElapsedTime, 1000)
}

const updateElapsedTime = () => {
  if (dedupStartedAt.value) {
    const startedMs = new Date(dedupStartedAt.value).getTime()
    elapsedTime.value = Math.floor((Date.now() - startedMs) / 1000)
  }
}

const stopTimer = () => {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  // 最后更新一次时间
  updateElapsedTime()
}

const formatTime = (seconds: number): string => {
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  if (hrs > 0) {
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

const formatPercent = (progress: number): string => {
  return progress.toFixed(2) + '%'
}

const runDedup = async () => {
  try {
    const response = await fetch('/api/review/run-dedup', {
      method: 'POST',
    })
    const data = await response.json()
    if (data.success) {
      dedupRunning.value = true
      dedupProgress.value = 0
      dedupStep.value = '初始化...'
      dedupDetails.value = null
      startDedupPolling()
    }
  } catch (error) {
    console.error('Failed to start deduplication:', error)
  }
}

const fetchDedupProgress = async () => {
  try {
    const response = await fetch('/api/review/dedup-progress')
    const data = await response.json()
    dedupProgress.value = data.progress || 0
    dedupStep.value = data.step || ''
    dedupStatus.value = data.status || 'idle'
    dedupDetails.value = data.details || null

    // 基于后端时间戳计算已耗时
    if (data.started_at && dedupStartedAt.value !== data.started_at) {
      dedupStartedAt.value = data.started_at
      startTimer()
    }

    if (data.status === 'completed' || data.status === 'failed') {
      dedupRunning.value = false
      if (data.results) {
        dedupResults.value = data.results
      }
      stopDedupPolling()
      stopTimer()
      await refreshAll()
    }
  } catch (error) {
    console.error('Failed to fetch dedup progress:', error)
  }
}

const startDedupPolling = () => {
  if (dedupPollTimer) {
    clearInterval(dedupPollTimer)
  }
  dedupPollTimer = window.setInterval(fetchDedupProgress, 1000)
}

const stopDedupPolling = () => {
  if (dedupPollTimer) {
    clearInterval(dedupPollTimer)
    dedupPollTimer = null
  }
}

// Check progress on mount in case dedup was started in another session
const checkInitialProgress = async () => {
  await fetchDedupProgress()
  if (dedupStatus.value === 'running') {
    dedupRunning.value = true
    startDedupPolling()
    // 计时器由 fetchDedupProgress 中的 started_at 自动触发
  }
}

const fetchItems = async () => {
  try {
    const params = new URLSearchParams()
    if (activeTab.value) params.append('status', activeTab.value)
    if (reviewType.value) params.append('review_type', reviewType.value)
    params.append('page', page.value.toString())
    params.append('size', size.value.toString())

    const response = await fetch(`/api/review?${params}`)
    const data = await response.json()
    items.value = data.items || []
    total.value = data.total || 0
    page.value = data.page || 1
  } catch (error) {
    console.error('Failed to fetch review items:', error)
  }
}

const refreshAll = async () => {
  await Promise.all([fetchItems(), statsRef.value?.fetchStats()])
}

const onTabChange = (tab: string) => {
  activeTab.value = tab
  page.value = 1
  selectedIds.value = []
  fetchItems()
}

const onFilterChange = () => {
  page.value = 1
  selectedIds.value = []
  fetchItems()
}

const onPageChange = (newPage: number) => {
  page.value = newPage
  fetchItems()
}

const onToggleSelect = (id: number) => {
  const index = selectedIds.value.indexOf(id)
  if (index > -1) {
    selectedIds.value.splice(index, 1)
  } else {
    selectedIds.value.push(id)
  }
}

const onToggleSelectAll = (selected: boolean) => {
  if (selected) {
    selectedIds.value = items.value.map((item) => item.id)
  } else {
    selectedIds.value = []
  }
}

const onClearSelection = () => {
  selectedIds.value = []
}

const onApprove = async (id: number) => {
  try {
    const response = await fetch(`/api/review/${id}/approve`, {
      method: 'POST',
    })
    if (response.ok) {
      await refreshAll()
      selectedIds.value = selectedIds.value.filter((i) => i !== id)
    }
  } catch (error) {
    console.error('Failed to approve:', error)
  }
}

const onReject = async (id: number) => {
  try {
    const response = await fetch(`/api/review/${id}/reject`, {
      method: 'POST',
    })
    if (response.ok) {
      await refreshAll()
      selectedIds.value = selectedIds.value.filter((i) => i !== id)
    }
  } catch (error) {
    console.error('Failed to reject:', error)
  }
}

const onBatchApprove = async (ids: number[]) => {
  try {
    const response = await fetch('/api/review/batch-approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    if (response.ok) {
      await refreshAll()
      selectedIds.value = []
    }
  } catch (error) {
    console.error('Failed to batch approve:', error)
  }
}

const onBatchReject = async (ids: number[]) => {
  try {
    const response = await fetch('/api/review/batch-reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    if (response.ok) {
      await refreshAll()
      selectedIds.value = []
    }
  } catch (error) {
    console.error('Failed to batch reject:', error)
  }
}

onMounted(() => {
  fetchItems()
  checkInitialProgress()
})

onUnmounted(() => {
  stopDedupPolling()
  stopTimer()
})
</script>

<style scoped>
.review-queue {
  min-height: 100vh;
  background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
  padding: 32px;
}

.page-header {
  margin-bottom: 32px;
}

.dedup-section {
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}

.dedup-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  background: linear-gradient(135deg, #89b4fa 0%, #74c7ec 100%);
  border: none;
  border-radius: 8px;
  color: #11111b;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dedup-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(137, 180, 250, 0.3);
}

.dedup-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(17, 17, 27, 0.3);
  border-top-color: #11111b;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.dedup-progress {
  margin-top: 16px;
}

.progress-bar-container {
  width: 100%;
  height: 8px;
  background: #313244;
  border-radius: 4px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #89b4fa, #a6e3a1);
  transition: width 0.3s ease;
  border-radius: 4px;
}

.progress-text {
  margin-top: 8px;
  font-size: 12px;
  color: #7f849c;
  text-align: center;
}

.progress-percent {
  margin-left: 12px;
  color: #a6e3a1;
  font-weight: 700;
  font-size: 13px;
  font-family: monospace;
}

.progress-details {
  margin-top: 4px;
  font-size: 11px;
  color: #a6e3a1;
  text-align: center;
  font-family: monospace;
}

.progress-timer {
  margin-top: 4px;
  font-size: 11px;
  color: #f9e2af;
  text-align: center;
  font-family: monospace;
  font-weight: 600;
}

.dedup-results {
  display: flex;
  gap: 20px;
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #313244;
}

.result-card {
  flex: 1;
  text-align: center;
  padding: 16px;
  background: rgba(137, 180, 250, 0.1);
  border-radius: 8px;
  border: 1px solid rgba(137, 180, 250, 0.2);
}

.result-number {
  font-size: 32px;
  font-weight: 700;
  color: #89b4fa;
  line-height: 1;
}

.result-label {
  margin-top: 8px;
  font-size: 12px;
  color: #7f849c;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 8px 0;
}

.page-subtitle {
  font-size: 14px;
  color: #7f849c;
  margin: 0;
}

.filter-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 16px;
}

.tabs {
  display: flex;
  gap: 4px;
  background: #1e1e2e;
  padding: 4px;
  border-radius: 10px;
  border: 1px solid #313244;
}

.tab-btn {
  padding: 10px 20px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #7f849c;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  color: #cdd6f4;
}

.tab-btn.active {
  background: #313244;
  color: #89b4fa;
  font-weight: 600;
}

.type-filter {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-label {
  font-size: 14px;
  color: #7f849c;
}

.filter-select {
  padding: 10px 16px;
  background: #1e1e2e;
  border: 1px solid #313244;
  border-radius: 8px;
  color: #cdd6f4;
  font-size: 14px;
  cursor: pointer;
  min-width: 140px;
}

.filter-select:hover {
  border-color: #45475a;
}

.filter-select:focus {
  outline: none;
  border-color: #89b4fa;
}
</style>
