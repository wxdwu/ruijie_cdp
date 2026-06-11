<template>
  <div class="review-stats">
    <div class="stats-grid">
      <div class="stat-card pending">
        <div class="stat-icon">⏳</div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.pending || 0 }}</div>
          <div class="stat-label">待审核</div>
        </div>
      </div>
      <div class="stat-card auto-merged">
        <div class="stat-icon">✅</div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.auto_merged || 0 }}</div>
          <div class="stat-label">自动合并</div>
        </div>
      </div>
      <div class="stat-card rejected">
        <div class="stat-icon">❌</div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.rejected || 0 }}</div>
          <div class="stat-label">已拒绝</div>
        </div>
      </div>
      <div class="stat-card need-review">
        <div class="stat-icon">🔍</div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.need_review || 0 }}</div>
          <div class="stat-label">需要人工审核</div>
        </div>
      </div>
      <div class="stat-card total">
        <div class="stat-icon">📊</div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.total || 0 }}</div>
          <div class="stat-label">总计</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

const stats = ref({
  pending: 0,
  auto_merged: 0,
  rejected: 0,
  need_review: 0,
  total: 0,
})

const fetchStats = async () => {
  try {
    const response = await fetch('/api/review/stats')
    const data = await response.json()
    stats.value = data
  } catch (error) {
    console.error('Failed to fetch stats:', error)
  }
}

onMounted(() => {
  fetchStats()
})

defineExpose({ fetchStats })
</script>

<style scoped>
.review-stats {
  margin-bottom: 24px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: #1e1e2e;
  border-radius: 12px;
  border: 1px solid #313244;
  transition: all 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.stat-icon {
  font-size: 32px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 10px;
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #9399b2;
  margin-top: 4px;
}

.stat-card.pending {
  border-left: 4px solid #f5c2e7;
}

.stat-card.auto-merged {
  border-left: 4px solid #a6e3a1;
}

.stat-card.rejected {
  border-left: 4px solid #f38ba8;
}

.stat-card.need-review {
  border-left: 4px solid #fab387;
}

.stat-card.total {
  border-left: 4px solid #89b4fa;
}
</style>
