<template>
  <div class="content-effect">
    <div class="table-header">
      <h3 class="table-title">内容互动效果</h3>
    </div>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>渠道</th>
            <th>总互动</th>
            <th>独立客户</th>
            <th>点击量</th>
            <th>打开量</th>
            <th>下载量</th>
            <th>点击率</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in data.data" :key="item.channel">
            <td>
              <span class="channel-tag">{{ item.channel }}</span>
            </td>
            <td class="number">{{ item.total_interactions.toLocaleString() }}</td>
            <td class="number">{{ item.unique_customers.toLocaleString() }}</td>
            <td class="number">{{ item.clicks.toLocaleString() }}</td>
            <td class="number">{{ item.opens.toLocaleString() }}</td>
            <td class="number">{{ item.downloads.toLocaleString() }}</td>
            <td>
              <span class="rate-badge" :class="getRateClass(item.click_rate)">
                {{ item.click_rate }}%
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data: {
    type: Object,
    default: () => ({ data: [] })
  }
})

const getRateClass = (rate) => {
  if (rate >= 20) return 'high'
  if (rate >= 10) return 'medium'
  return 'low'
}
</script>

<style scoped>
.content-effect {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
}

.table-header {
  margin-bottom: 16px;
}

.table-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
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

.number {
  font-weight: 500;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.channel-tag {
  display: inline-block;
  padding: 4px 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent);
}

.rate-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.rate-badge.high {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

.rate-badge.medium {
  background: rgba(250, 204, 21, 0.2);
  color: #facc15;
}

.rate-badge.low {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}
</style>
