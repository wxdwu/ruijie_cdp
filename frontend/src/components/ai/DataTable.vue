<template>
  <div class="data-table">
    <div class="result-header">
      <div class="result-info">
        <span class="result-count">共 {{ total }} 条结果</span>
      </div>
      <button
        v-if="showExport && total > 0"
        @click="$emit('export')"
        class="export-btn"
      >
        📥 导出Excel
      </button>
    </div>

    <div v-if="paginatedItems.length === 0" class="empty-state">
      <div class="empty-icon">🔍</div>
      <div class="empty-text">没有找到匹配的数据</div>
    </div>
    <div v-else class="table-wrapper">
      <table>
        <thead>
          <tr>
            <th class="index-col">#</th>
            <th v-for="(value, key) in paginatedItems[0]" :key="key">
              {{ formatHeader(key) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in paginatedItems" :key="index" @click="$emit('row-click', item)" class="clickable-row">
            <td class="index-col">{{ (page - 1) * pageSize + index + 1 }}</td>
            <td v-for="(value, key) in item" :key="key" :title="formatValue(value)">
              <span v-if="key === 'customer_name'" class="customer-link">{{ formatValue(value) }}</span>
              <span v-else>{{ formatValue(value) }}</span>
            </td>
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
    <div v-else-if="total > 0" class="pagination">
      <span class="total">共 {{ total }} 条</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  items: any[]
  total: number
  page?: number
  pageSize?: number
  showExport?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  page: 1,
  pageSize: 20,
  showExport: false,
})

defineEmits<{
  (e: 'export'): void
  (e: 'page-change', page: number): void
  (e: 'row-click', item: any): void
}>()

// 前端分页：根据 page 和 pageSize 计算当前页的数据
const paginatedItems = computed(() => {
  const start = (props.page - 1) * props.pageSize
  const end = start + props.pageSize
  return props.items.slice(start, end)
})

function formatHeader(key: string): string {
  // 将字段名转换为中文显示
  const headerMap: Record<string, string> = {
    customer_name: '客户名称',
    contact_name: '联系人姓名',
    mobile: '手机号',
    email: '邮箱',
    department: '部门',
    position: '职位',
    purchase_role: '采购角色',
    role_category: '角色类别',
    source_table: '来源表',
    channel: '互动渠道',
    behavior_type: '行为类型',
    content: '互动内容',
    event_time: '互动时间',
    is_high_value: '高价值',
    interaction_count: '总互动次数',
    interaction_count_30d: '近30天互动',
    last_interaction_time: '最近互动时间',
    activity_level: '活跃度',
    intent_level: '意向等级',
    lead_stage: '线索阶段',
    linkflow_contact_id: 'Linkflow ID',
    zhique_matched: '智能体匹配',
  }
  return headerMap[key] || key
}

function formatValue(value: any): string {
  if (value === null || value === undefined) {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否'
  }
  if (value instanceof Date) {
    return value.toLocaleString('zh-CN')
  }
  return String(value)
}
</script>

<style scoped>
.data-table {
  background: var(--surface);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border);
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

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
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
  color: var(--text);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

td {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

tbody tr {
  transition: background 0.2s;
  cursor: pointer;
}

tbody tr:hover {
  background: var(--background);
}

.clickable-row:hover {
  background: rgba(59, 130, 246, 0.05);
}

.index-col {
  width: 50px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

.customer-link {
  color: var(--primary);
  font-weight: 500;
  text-decoration: none;
}

.customer-link:hover {
  text-decoration: underline;
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

.total {
  font-size: 13px;
  color: var(--muted);
}
</style>
