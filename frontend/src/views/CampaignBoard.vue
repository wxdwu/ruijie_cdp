<template>
  <div class="campaign-board">
    <div class="board-header">
      <div>
        <h1 class="page-title">营销活动看板</h1>
        <p class="page-subtitle">实时监控营销活动效果，洞察客户转化数据</p>
      </div>
      <div class="header-actions">
        <select class="date-select">
          <option>最近 7 天</option>
          <option>最近 30 天</option>
          <option>最近 90 天</option>
          <option>本年度</option>
        </select>
        <button class="refresh-btn" @click="fetchData">
          <i class="fas fa-sync-alt"></i>
          刷新
        </button>
      </div>
    </div>

    <!-- KPIs -->
    <CampaignKpis :data="kpiData" />

    <!-- Charts Grid -->
    <div class="charts-grid">
      <div class="chart-column">
        <FunnelChart :data="funnelData" />
      </div>
      <div class="chart-column">
        <ChannelPie :data="channelData" />
      </div>
      <div class="chart-column full-width">
        <RoleCoverageChart :data="roleData" />
      </div>
    </div>

    <!-- Content Effect Table -->
    <ContentEffectTable :data="contentData" />

    <!-- Customer Follow-up Table -->
    <CustomerFollowupTable :data="customerData" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import CampaignKpis from '../components/campaign/CampaignKpis.vue'
import FunnelChart from '../components/campaign/FunnelChart.vue'
import ChannelPie from '../components/campaign/ChannelPie.vue'
import RoleCoverageChart from '../components/campaign/RoleCoverageChart.vue'
import ContentEffectTable from '../components/campaign/ContentEffectTable.vue'
import CustomerFollowupTable from '../components/campaign/CustomerFollowupTable.vue'

const kpiData = ref({})
const funnelData = ref({ stages: [], total: 0 })
const channelData = ref({ channels: [], total: 0 })
const roleData = ref({ roles: [], total_customers: 0 })
const contentData = ref({ data: [] })
const customerData = ref({ flat: [] })

const API_BASE = 'http://localhost:8000/api/campaign'

const fetchData = async () => {
  try {
    // Fetch KPIs
    const kpisResponse = await fetch(`${API_BASE}/kpis`)
    if (kpisResponse.ok) {
      kpiData.value = await kpisResponse.json()
    }

    // Fetch Funnel Distribution
    const funnelResponse = await fetch(`${API_BASE}/funnel-distribution`)
    if (funnelResponse.ok) {
      funnelData.value = await funnelResponse.json()
    }

    // Fetch Channel Distribution
    const channelResponse = await fetch(`${API_BASE}/channel-distribution`)
    if (channelResponse.ok) {
      channelData.value = await channelResponse.json()
    }

    // Fetch Role Coverage
    const roleResponse = await fetch(`${API_BASE}/role-coverage`)
    if (roleResponse.ok) {
      roleData.value = await roleResponse.json()
    }

    // Fetch Content Effect
    const contentResponse = await fetch(`${API_BASE}/content-effect`)
    if (contentResponse.ok) {
      contentData.value = await contentResponse.json()
    }

    // Fetch Customers by Stage
    const customerResponse = await fetch(`${API_BASE}/customers-by-stage`)
    if (customerResponse.ok) {
      customerData.value = await customerResponse.json()
    }
  } catch (error) {
    console.error('Failed to fetch campaign data:', error)
    // Use mock data if API fails
    useMockData()
  }
}

const useMockData = () => {
  kpiData.value = {
    total_customers: 1234,
    total_interactions: 56789,
    total_opportunities: 456,
    won_amount: 12345678,
    conversion_rate: 23.5
  }

  funnelData.value = {
    stages: [
      { stage: 'Awareness', count: 500, percentage: 40.5 },
      { stage: 'Consideration', count: 350, percentage: 28.4 },
      { stage: 'Decision', count: 200, percentage: 16.2 },
      { stage: 'Proposal', count: 100, percentage: 8.1 },
      { stage: 'Negotiation', count: 50, percentage: 4.1 },
      { stage: 'Closed Won', count: 34, percentage: 2.7 }
    ],
    total: 1234
  }

  channelData.value = {
    channels: [
      { channel: 'Email', count: 25000, percentage: 44.0 },
      { channel: 'WeChat', count: 15000, percentage: 26.4 },
      { channel: 'Webinar', count: 8000, percentage: 14.1 },
      { channel: 'Website', count: 5789, percentage: 10.2 },
      { channel: 'Direct Mail', count: 3000, percentage: 5.3 }
    ],
    total: 56789
  }

  roleData.value = {
    roles: [
      { role: '张三', customer_count: 150, total_interactions: 5200, total_opportunity_value: 2500000, coverage_percentage: 12.2 },
      { role: '李四', customer_count: 130, total_interactions: 4800, total_opportunity_value: 2100000, coverage_percentage: 10.5 },
      { role: '王五', customer_count: 110, total_interactions: 4100, total_opportunity_value: 1800000, coverage_percentage: 8.9 },
      { role: '赵六', customer_count: 95, total_interactions: 3500, total_opportunity_value: 1500000, coverage_percentage: 7.7 },
      { role: '钱七', customer_count: 85, total_interactions: 3100, total_opportunity_value: 1300000, coverage_percentage: 6.9 }
    ],
    total_customers: 1234
  }

  contentData.value = {
    data: [
      { channel: 'Email', total_interactions: 25000, unique_customers: 850, clicks: 5200, opens: 18000, downloads: 1200, click_rate: 20.8 },
      { channel: 'WeChat', total_interactions: 15000, unique_customers: 620, clicks: 2800, opens: 11000, downloads: 800, click_rate: 18.7 },
      { channel: 'Webinar', total_interactions: 8000, unique_customers: 340, clicks: 1500, opens: 6000, downloads: 450, click_rate: 18.8 },
      { channel: 'Website', total_interactions: 5789, unique_customers: 280, clicks: 950, opens: 4200, downloads: 320, click_rate: 16.4 },
      { channel: 'Direct Mail', total_interactions: 3000, unique_customers: 150, clicks: 400, opens: 2200, downloads: 180, click_rate: 13.3 }
    ]
  }

  customerData.value = {
    flat: [
      { stage: 'Awareness', customer_name: '客户A', company_name: '科技有限公司', intent_level: 'High', engagement_score: 85.5, opportunity_amount: 500000 },
      { stage: 'Consideration', customer_name: '客户B', company_name: '创新企业', intent_level: 'Medium', engagement_score: 72.3, opportunity_amount: 350000 },
      { stage: 'Decision', customer_name: '客户C', company_name: '未来集团', intent_level: 'High', engagement_score: 88.2, opportunity_amount: 800000 },
      { stage: 'Proposal', customer_name: '客户D', company_name: '智慧科技', intent_level: 'Medium', engagement_score: 65.8, opportunity_amount: 280000 },
      { stage: 'Negotiation', customer_name: '客户E', company_name: '先导股份', intent_level: 'High', engagement_score: 92.1, opportunity_amount: 1200000 },
      { stage: 'Closed Won', customer_name: '客户F', company_name: '鼎盛科技', intent_level: 'High', engagement_score: 95.5, opportunity_amount: 2000000 }
    ]
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.campaign-board {
  padding: 24px;
  min-height: 100vh;
}

.board-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px 0;
}

.page-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.date-select {
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.refresh-btn:hover {
  background: var(--accent-hover);
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.chart-column {
  min-width: 0;
}

.chart-column.full-width {
  grid-column: 1 / -1;
}

@media (max-width: 1024px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .campaign-board {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }
}
</style>
