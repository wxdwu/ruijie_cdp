<template>
  <div class="customer-followup">
    <div class="table-header">
      <h3 class="table-title">客户跟进列表</h3>
      <div class="filter-grid">
        <label class="filter-field">
          <span class="filter-label">阶段</span>
          <select v-model="currentStage" class="filter-control">
            <option v-for="stage in stages" :key="stage" :value="stage">
              {{ stage }}
            </option>
          </select>
        </label>

        <label class="filter-field">
          <span class="filter-label">负责人</span>
          <select v-model="currentOwner" class="filter-control">
            <option v-for="owner in owners" :key="owner" :value="owner">
              {{ owner }}
            </option>
          </select>
        </label>

        <label class="filter-field search-field">
          <span class="filter-label">搜索客户</span>
          <input
            v-model.trim="searchKeyword"
            class="filter-control"
            type="search"
            placeholder="输入客户名称"
          />
        </label>
      </div>
    </div>
    <div class="table-container">
      <table>
        <colgroup>
          <col class="col-customer" />
          <col class="col-stage" />
          <col class="col-role" />
          <col class="col-intent" />
          <col class="col-interaction" />
          <col class="col-basis" />
        </colgroup>
        <thead>
          <tr>
            <th>客户名称</th>
            <th>采购阶段</th>
            <th>关键角色覆盖</th>
            <th>合作意向</th>
            <th>最近互动</th>
            <th>渠道 / 跟进依据</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="customer in filteredCustomers" :key="customer.customer_name">
            <td>
              <div class="customer-name">
                <div class="customer-avatar">
                  {{ customer.customer_name.charAt(0) }}
                </div>
                <span>{{ customer.customer_name }}</span>
              </div>
            </td>
            <td>
              <span class="stage-badge" :class="getStageClass(customer.stage)">
                {{ customer.stage }}
              </span>
            </td>
            <td>
              <span class="role-coverage-value">{{ getRoleCoverage(customer) }}</span>
            </td>
            <td>
              <div class="intent-summary">
                <span class="intent-badge" :class="getIntentLevel(customer)">
                  {{ getIntentLevel(customer) }}
                </span>
                <span class="intent-score">
                  {{ formatIntentScore(customer) }}
                </span>
              </div>
            </td>
            <td>
              <span class="last-interaction">{{ formatLastInteraction(customer) }}</span>
            </td>
            <td>
              <div class="followup-source">
                <span v-if="getChannel(customer)" class="channel-tag">
                  {{ getChannel(customer) }}
                </span>
                <span class="followup-basis">{{ getFollowupBasis(customer) }}</span>
              </div>
            </td>
          </tr>
          <tr v-if="filteredCustomers.length === 0">
            <td class="empty-result" colspan="6">暂无符合条件的客户</td>
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
const currentOwner = ref('全部')
const searchKeyword = ref('')

const stages = computed(() => {
  const uniqueStages = [...new Set(props.data.flat.map(c => c.stage))]
    .filter(Boolean)
    .sort((stageA, stageB) => {
      const numberA = Number(stageA.match(/阶段\s*(\d+)/)?.[1])
      const numberB = Number(stageB.match(/阶段\s*(\d+)/)?.[1])
      const hasNumberA = Number.isFinite(numberA)
      const hasNumberB = Number.isFinite(numberB)

      if (hasNumberA && hasNumberB) return numberA - numberB
      if (hasNumberA) return -1
      if (hasNumberB) return 1
      return stageA.localeCompare(stageB, 'zh-CN')
    })
  return ['全部', ...uniqueStages]
})

const owners = computed(() => {
  const uniqueOwners = props.data.flat
    .map(customer => customer.owner_name || customer.owner)
    .filter(Boolean)
  return ['全部', ...new Set(uniqueOwners)]
})

const filteredCustomers = computed(() => {
  const keyword = searchKeyword.value.toLowerCase()

  return props.data.flat
    .filter(customer => (
      currentStage.value === '全部' || customer.stage === currentStage.value
    ))
    .filter(customer => {
      const owner = customer.owner_name || customer.owner
      return currentOwner.value === '全部' || owner === currentOwner.value
    })
    .filter(customer => {
      if (!keyword) return true
      return (customer.customer_name || '').toLowerCase().includes(keyword)
    })
    .slice(0, 20)
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

const formatIntentScore = (customer) => {
  const score = customer.intent_score ?? customer.engagement_score
  return Number.isFinite(Number(score)) ? `${Number(score).toFixed(0)} 分` : '暂无评分'
}

const getIntentLevel = (customer) => {
  const level = customer.intent_level
  return !level || level === '无' ? '低' : level
}

const getRoleCoverage = (customer) => (
  customer.role_coverage || customer.key_role_coverage || '—'
)

const formatLastInteraction = (customer) => {
  const value = customer.last_interaction_time || customer.recent_interaction
  if (!value) return '—'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date)
}

const getChannel = (customer) => (
  customer.channel || customer.last_interaction_channel || ''
)

const getFollowupBasis = (customer) => (
  customer.followup_basis
  || customer.follow_up_basis
  || customer.last_interaction_content
  || customer.behavior_type
  || '—'
)
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
  flex-direction: column;
  align-items: stretch;
  margin-bottom: 16px;
  gap: 16px;
}

.table-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.filter-grid {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(160px, 1fr) minmax(220px, 1.3fr);
  gap: 14px;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.filter-label {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1;
}

.filter-control {
  width: 100%;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 10px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

select.filter-control {
  cursor: pointer;
}

.filter-control:hover {
  border-color: var(--accent);
}

.filter-control:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(79, 172, 254, 0.12);
}

.filter-control::placeholder {
  color: var(--text-muted);
}

.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  table-layout: fixed;
}

.col-customer {
  width: 25%;
}

.col-stage {
  width: 19%;
}

.col-role {
  width: 13%;
}

.col-intent {
  width: 14%;
}

.col-interaction {
  width: 18%;
}

.col-basis {
  width: 11%;
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
  vertical-align: middle;
}

tr:hover {
  background: var(--bg-hover);
}

.empty-result {
  padding: 32px 12px;
  color: var(--text-muted);
  text-align: center;
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

.intent-badge.高 {
  background: rgba(67, 233, 123, 0.2);
  color: #43e97b;
}

.intent-badge.中 {
  background: rgba(250, 204, 21, 0.2);
  color: #facc15;
}

.intent-badge.低,
.intent-badge.无 {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}

.intent-summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.intent-score {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
}

.role-coverage-value,
.last-interaction {
  color: var(--text-muted);
  font-size: 13px;
  white-space: nowrap;
}

.followup-source {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.channel-tag {
  flex-shrink: 0;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(79, 172, 254, 0.14);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
}

.followup-basis {
  min-width: 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
