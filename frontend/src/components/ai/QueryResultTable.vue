<template>
  <div class="query-result-table">
    <div class="result-header">
      <div class="result-info">
        <span class="result-count">共 {{ total }} 条结果</span>
        <span v-if="page > 1" class="result-page">第 {{ page }} 页</span>
      </div>
      <button
        v-if="showExport && total > 0"
        @click="$emit('export')"
        class="export-btn"
      >
        📥 导出Excel
      </button>
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <div class="empty-icon">🔍</div>
      <div class="empty-text">没有找到匹配的客户</div>
    </div>

    <div v-else class="table-container">
      <table>
        <thead>
          <tr>
            <th>客户名称</th>
            <th>行业</th>
            <th>区域</th>
            <th>购买阶段</th>
            <th>意向等级</th>
            <th>30天互动</th>
            <th>最近渠道</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id" @click="$emit('row-click', item)">
            <td class="customer-name">{{ item.customer_name }}</td>
            <td><span class="tag industry">{{ item.industry || '-' }}</span></td>
            <td><span class="tag region">{{ item.region || '-' }}</span></td>
            <td><span class="tag stage">{{ item.purchase_stage || '-' }}</span></td>
            <td><span class="tag intent">{{ item.intent_level || '-' }}</span></td>
            <td class="interaction-count">{{ item.interaction_count_30d || 0 }}</td>
            <td><span class="tag channel">{{ item.last_interaction_channel || '-' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="total > pageSize" class="pagination">
      <button
        :disabled="page <= 1"
        @click="$emit('page-change', page - 1)"
        class="page-btn"
      >
        上一页
      </button>
      <span class="page-info">
        {{ (page - 1) * pageSize + 1 }} - {{ Math.min(page * pageSize, total) }} / {{ total }}
      </span>
      <button
        :disabled="page * pageSize >= total"
        @click="$emit('page-change', page + 1)"
        class="page-btn"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  items: any[]
  total: number
  page: number
  pageSize: number
  showExport?: boolean
}>()

defineEmits<{
  (e: 'export'): void
  (e: 'page-change', page: number): void
  (e: 'row-click', item: any): void
}>()
</script>

<style scoped>
.query-result-table {
  background: var(--surface);
  border-radius: 12px;
  border: 1px solid var(--border);
  overflow: hidden;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--background);
}

.result-info {
  display: flex;
  gap: 12px;
  align-items: center;
}

.result-count {
  font-weight: 600;
  color: var(--text);
}

.result-page {
  color: var(--muted);
  font-size: 14px;
}

.export-btn {
  padding: 8px 16px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.export-btn:hover {
  background: var(--primary-dark);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  color: var(--muted);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-text {
  font-size: 16px;
}

.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

thead {
  background: var(--background);
  position: sticky;
  top: 0;
}

th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}

tbody tr {
  cursor: pointer;
  transition: background 0.2s;
}

tbody tr:hover {
  background: var(--background);
}

.customer-name {
  font-weight: 600;
  color: var(--primary);
}

.interaction-count {
  font-weight: 600;
  text-align: center;
}

.tag {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.tag.industry {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.tag.region {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.tag.stage {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.tag.intent {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.tag.channel {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  background: var(--background);
}

.page-btn {
  padding: 8px 16px;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: 14px;
  color: var(--muted);
}
</style>
