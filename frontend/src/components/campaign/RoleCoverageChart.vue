<template>
  <div class="role-coverage">
    <div class="chart-header">
      <h3 class="chart-title">角色覆盖统计</h3>
      <span class="chart-subtitle">总计: {{ data.total_customers || 0 }} 客户</span>
    </div>
    <div class="role-list">
      <div class="role-item" v-for="role in paginatedRoles" :key="role.role">
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
    <div v-if="totalPages > 1" class="role-pagination">
      <button
        class="page-btn"
        type="button"
        :disabled="currentPage === 1"
        @click="currentPage--"
      >
        上一页
      </button>
      <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button
        class="page-btn"
        type="button"
        :disabled="currentPage === totalPages"
        @click="currentPage++"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({ roles: [], total_customers: 0 })
  }
})

const PAGE_SIZE = 5
const currentPage = ref(1)

const roles = computed(() => props.data.roles || [])
const totalPages = computed(() => Math.max(1, Math.ceil(roles.value.length / PAGE_SIZE)))
const paginatedRoles = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return roles.value.slice(start, start + PAGE_SIZE)
})

watch(totalPages, (pages) => {
  if (currentPage.value > pages) {
    currentPage.value = pages
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

.role-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding-top: 20px;
}

.page-btn {
  padding: 8px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.page-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.page-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.page-info {
  min-width: 84px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}
</style>
