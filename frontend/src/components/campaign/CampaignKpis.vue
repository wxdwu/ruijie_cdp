<template>
  <div class="kpis-grid">
    <div class="kpi-card" v-for="(kpi, key) in kpis" :key="key">
      <div class="kpi-icon" :class="key">
        <i :class="kpi.icon"></i>
      </div>
      <div class="kpi-content">
        <div class="kpi-value">{{ kpi.formatted }}</div>
        <div class="kpi-label">{{ kpi.label }}</div>
        <div class="kpi-trend" :class="kpi.trend > 0 ? 'up' : 'down'" v-if="kpi.trend !== 0">
          <span>{{ kpi.trend > 0 ? '↑' : '↓' }} {{ Math.abs(kpi.trend) }}%</span>
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
    default: () => ({})
  }
})

const kpis = computed(() => ({
  total_customers: {
    label: '总客户数',
    value: props.data.total_customers || 0,
    formatted: (props.data.total_customers || 0).toLocaleString(),
    icon: 'fas fa-users',
    trend: 12.5
  },
  total_interactions: {
    label: '互动总量',
    value: props.data.total_interactions || 0,
    formatted: (props.data.total_interactions || 0).toLocaleString(),
    icon: 'fas fa-comments',
    trend: 8.3
  },
  total_opportunities: {
    label: '商机总数',
    value: props.data.total_opportunities || 0,
    formatted: (props.data.total_opportunities || 0).toLocaleString(),
    icon: 'fas fa-lightbulb',
    trend: 15.2
  },
  won_amount: {
    label: '成交金额',
    value: props.data.won_amount || 0,
    formatted: '¥' + ((props.data.won_amount || 0).toLocaleString()),
    icon: 'fas fa-dollar-sign',
    trend: 22.1
  },
  conversion_rate: {
    label: '转化率',
    value: props.data.conversion_rate || 0,
    formatted: (props.data.conversion_rate || 0) + '%',
    icon: 'fas fa-chart-line',
    trend: 5.7
  }
}))
</script>

<style scoped>
.kpis-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: all 0.3s ease;
}

.kpi-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.kpi-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.kpi-icon.total_customers {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.kpi-icon.total_interactions {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: white;
}

.kpi-icon.total_opportunities {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
}

.kpi-icon.won_amount {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
  color: white;
}

.kpi-icon.conversion_rate {
  background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
  color: white;
}

.kpi-content {
  flex: 1;
}

.kpi-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.kpi-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.kpi-trend {
  font-size: 12px;
  font-weight: 500;
}

.kpi-trend.up {
  color: #4ade80;
}

.kpi-trend.down {
  color: #f87171;
}

@media (max-width: 1200px) {
  .kpis-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .kpis-grid {
    grid-template-columns: 1fr;
  }
}
</style>
