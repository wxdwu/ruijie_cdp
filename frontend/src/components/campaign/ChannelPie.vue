<template>
  <div class="channel-pie">
    <div class="chart-header">
      <h3 class="chart-title">渠道分布</h3>
      <span class="chart-subtitle">总计: {{ data.total || 0 }} 互动</span>
    </div>
    <div class="channel-list">
      <div class="channel-item" v-for="channel in data.channels" :key="channel.channel">
        <div class="channel-header">
          <span class="channel-name">{{ channel.channel }}</span>
          <span class="channel-percentage">{{ channel.percentage }}%</span>
        </div>
        <div class="channel-bar-container">
          <div
            class="channel-bar"
            :style="{ width: channel.percentage + '%' }"
          ></div>
        </div>
        <div class="channel-stats">
          <span>{{ channel.count }} 次互动</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data: {
    type: Object,
    default: () => ({ channels: [], total: 0 })
  }
})
</script>

<style scoped>
.channel-pie {
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

.channel-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.channel-item {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  transition: all 0.3s ease;
}

.channel-item:hover {
  background: var(--bg-hover);
}

.channel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.channel-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.channel-percentage {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
}

.channel-bar-container {
  height: 8px;
  background: var(--bg-hover);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.channel-bar {
  height: 100%;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.channel-stats {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
