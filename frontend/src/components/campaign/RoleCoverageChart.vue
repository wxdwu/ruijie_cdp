<template>
  <div class="role-coverage">
    <div class="chart-header">
      <h3 class="chart-title">角色覆盖统计</h3>
      <span class="chart-subtitle">总计: {{ data.total_customers || 0 }} 客户</span>
    </div>
    <div class="role-list">
      <div class="role-item" v-for="role in data.roles" :key="role.role">
        <div class="role-header">
          <div class="role-avatar">
            {{ role.role.charAt(0).toUpperCase() }}
          </div>
          <div class="role-info">
            <div class="role-name">{{ role.role }}</div>
            <div class="role-detail">
              {{ role.customer_count }} 客户 · {{ role.total_interactions }} 互动
            </div>
          </div>
          <div class="role-value">
            <div class="coverage-percent">{{ role.coverage_percentage }}%</div>
            <div class="opportunity-value">¥{{ role.total_opportunity_value.toLocaleString() }}</div>
          </div>
        </div>
        <div class="role-bar-container">
          <div
            class="role-bar"
            :style="{ width: role.coverage_percentage + '%' }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data: {
    type: Object,
    default: () => ({ roles: [], total_customers: 0 })
  }
})
</script>

<style scoped>
.role-coverage {
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

.role-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.role-item {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  transition: all 0.3s ease;
}

.role-item:hover {
  background: var(--bg-hover);
}

.role-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.role-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  flex-shrink: 0;
}

.role-info {
  flex: 1;
}

.role-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.role-detail {
  font-size: 12px;
  color: var(--text-muted);
}

.role-value {
  text-align: right;
}

.coverage-percent {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
}

.opportunity-value {
  font-size: 12px;
  color: var(--text-muted);
}

.role-bar-container {
  height: 6px;
  background: var(--bg-hover);
  border-radius: 3px;
  overflow: hidden;
}

.role-bar {
  height: 100%;
  background: linear-gradient(90deg, #43e97b 0%, #38f9d7 100%);
  border-radius: 3px;
  transition: width 0.5s ease;
}
</style>
