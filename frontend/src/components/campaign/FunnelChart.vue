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
      >
        <div class="stage-bar-track">
          <div
            class="stage-bar"
            :style="{ width: getStageWidth(index) + '%' }"
          ></div>
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
  const maxPercentage = Math.max(...stages.map(s => Number(s.percentage) || 0))
  const percentage = Number(stages[index].percentage) || 0
  if (maxPercentage <= 0) return 0
  return Math.max(2, (percentage / maxPercentage) * 100)
}
</script>

<style scoped>
.funnel-chart {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  height: 100%;
  min-height: 420px;
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
  gap: 12px;
}

.funnel-stage {
  transition: all 0.3s ease;
}

.funnel-stage:hover {
  filter: brightness(1.1);
}

.stage-bar-track {
  position: relative;
  height: 52px;
  overflow: hidden;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(101, 179, 255, 0.14);
}

.stage-bar {
  position: absolute;
  inset: 0 auto 0 0;
  min-width: 2%;
  background: linear-gradient(90deg, #65b3ff 0%, #7c6ee6 100%);
  border-radius: 8px;
  transition: width 0.45s ease;
}

.stage-info {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  width: 100%;
  height: 100%;
  padding: 0 14px;
}

.stage-name {
  font-size: 14px;
  font-weight: 600;
  color: white;
  line-height: 1.25;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.28);
}

.stage-count {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
</style>
