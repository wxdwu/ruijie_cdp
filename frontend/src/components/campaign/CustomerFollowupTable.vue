<template>
  <div class="customer-followup">
    <div class="table-header">
      <h3 class="table-title">客户跟进列表</h3>
      <div class="filter-tabs">
        <button
          v-for="stage in stages"
          :key="stage"
          :class="{ active: currentStage === stage }"
          @click="currentStage = stage"
        >
          {{ stage }}
        </button>
      </div>
    </div>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>客户名称</th>
            <th>公司名称</th>
            <th>阶段</th>
            <th>意向等级</th>
            <th>参与度评分</th>
            <th>商机金额</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="customer in filteredCustomers" :key="customer.customer_name">
            <td class="customer-name">
              <div class="customer-avatar">
                {{ customer.customer_name.charAt(0) }}
              </div>
              <span>{{ customer.customer_name }}</span>
            </td>
            <td>{{ customer.company_name }}</td>
            <td>
              <span class="stage-badge" :class="getStageClass(customer.stage)">
                {{ customer.stage }}
              </span>
            </td>
            <td>
              <span class="intent-badge" :class="customer.intent_level">
                {{ customer.intent_level }}
              </span>
            </td>
            <td>
              <div class="score-bar">
                <div
                  class="score-fill"
                  :style="{ width: Math.min(customer.engagement_score, 100) + '%' }"
                ></div>
                <span class="score-value">{{ (customer.engagement_score || 0).toFixed(1) }}</span>
              </div>
            </td>
            <td class="amount">¥{{ (customer.opportunity_amount || 0).toLocaleString() }}</td>
            <td>
              <button class="action-btn">查看</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({ flat: [] })
  }
})

const currentStage = ref('全部')

const stages = computed(() => {
  const uniqueStages = [...new Set(props.data.flat.map(c => c.stage))]
  return ['全部', ...uniqueStages]
})

const filteredCustomers = computed(() => {
  if (currentStage.value === '全部') {
    return props.data.flat.slice(0, 20)
  }
  return props.data.flat.filter(c => c.stage === currentStage.value).slice(0, 20)
})

const getStageClass = (stage) => {
  const stageMap = {
    'Awareness': 'awareness',
    'Consideration': 'consideration',
    'Decision': 'decision',
    'Proposal': 'proposal',
    'Negotiation': 'negotiation',
    'Closed Won': 'won',
    'Closed Lost': 'lost'
  }
  return stageMap[stage] || 'default'
}
</script>

<style scoped>
.customer-followup {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.table-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.filter-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-tabs button {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-muted);
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-tabs button:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.filter-tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}

.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th {
  text-align: left;
  padding: 12px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-color);
}

td {
  padding: 12px 8px;
  font-size: 14px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

tr:hover {
  background: var(--bg-hover);
}

.customer-name {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 500;
}

.customer-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.stage-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.stage-badge.awareness {
  background: rgba(102, 126, 234, 0.2);
  color: #667eea;
}

.stage-badge.consideration {
  background: rgba(118, 75, 162, 0.2);
  color: #764ba2;
}

.stage-badge.decision {
  background: rgba(240, 147, 251, 0.2);
  color: #f093fb;
}

.stage-badge.proposal {
  background: rgba(245, 87, 108, 0.2);
  color: #f5576c;
}

.stage-badge.negotiation {
  background: rgba(79, 172, 254, 0.2);
  color: #4facfe;
}

.stage-badge.won {
  background: rgba(67, 233, 123, 0.2);
  color: #43e97b;
}

.stage-badge.lost {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}

.intent-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.intent-badge.High {
  background: rgba(67, 233, 123, 0.2);
  color: #43e97b;
}

.intent-badge.Medium {
  background: rgba(250, 204, 21, 0.2);
  color: #facc15;
}

.intent-badge.Low {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}

.score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}

.score-fill {
  height: 6px;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  border-radius: 3px;
  flex: 1;
}

.score-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  min-width: 35px;
}

.amount {
  font-weight: 600;
  color: #43e97b;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.action-btn {
  padding: 6px 14px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: var(--accent-hover);
}
</style>
