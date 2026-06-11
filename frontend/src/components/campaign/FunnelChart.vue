<template>
  <div class="funnel-chart">
    <div class="chart-header">
      <h3 class="chart-title">客户阶段漏斗</h3>
      <span class="chart-subtitle">总计: {{ data.total || 0 }} 客户</span>
    </div>
    <div class="funnel-container">
      <div
        class="funnel-stage"
        v-for="(stage, index) in data.stages"
        :key="stage.stage"
        :style="{ width: getStageWidth(index) + '%' }"
      >
        <div class="stage-bar">
          <div class="stage-info">
            <span class="stage-name">{{ stage.stage }}</span>
            <span class="stage-count">{{ stage.count }} ({{ stage.percentage }}%)</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({ stages: [], total: 0 })
  }
})

const colors = [
  '#667eea',
  '#764ba2',
  '#f093fb',
  '#f5576c',
  '#4facfe',
  '#00f2fe',
  '#43e97b',
  '#38f9d7'
]

const getStageWidth = (index) => {
  const stages = props.data.stages || []
  if (stages.length === 0) return 100
  const maxCount = Math.max(...stages.map(s => s.count))
  const count = stages[index].count
  return Math.max(30, (count / maxCount) * 100)
}
</script>

<style scoped>
.funnel-chart {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  height: 100%;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.chart-subtitle {
  font-size: 13px;
  color: var(--text-muted);
}

.funnel-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.funnel-stage {
  transition: all 0.3s ease;
}

.funnel-stage:hover {
  filter: brightness(1.1);
}

.stage-bar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 8px;
  padding: 12px 16px;
  min-height: 56px;
  display: flex;
  align-items: center;
}

.stage-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.stage-name {
  font-size: 14px;
  font-weight: 600;
  color: white;
}

.stage-count {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
}
</style>
