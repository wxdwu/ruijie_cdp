<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import FieldHelpTooltip from '../components/customer/FieldHelpTooltip.vue'
import { getCampaignHelp } from '../components/campaign/campaignHelpConfig'
import { BASE_URL } from '../config'

const router = useRouter()
const API_BASE = `${BASE_URL}/api/campaign`

const filters = reactive({
  campaign_tag: '',
  start_date: '',
  end_date: '',
  channel: '',
  industry: '',
})
const customerFilters = reactive({
  stage: '',
  owner: '',
  keyword: '',
})

const loading = ref(false)
const filterOptions = ref({ campaigns: [], industries: [], channels: [], min_date: '', max_date: '' })
const kpiData = ref({})
const opportunityData = ref({ categories: [], total: 0 })
const channelData = ref({ channels: [], total: 0 })
const stageData = ref({ stages: [], total: 0 })
const roleData = ref({ roles: [], total_customers: 0 })
const tagData = ref({ signals: [] })
const contentData = ref({ data: [] })
const customerData = ref({ flat: [], total: 0, page: 1, page_size: 10, total_pages: 1, filter_options: { stages: [], owners: [] } })
const customerPage = ref(1)
const CUSTOMER_PAGE_SIZE = 10

const channelLabels = {
  web: '官网',
  email: '邮件',
  event: '直播/活动',
  wechat: '微信',
  '无渠道/未触达': '无渠道/未触达',
}

const kpiCards = computed(() => [
  {
    id: 'CMP-01',
    key: 'total_customers',
    label: '总客户数',
    value: formatNumber(kpiData.value.total_customers),
    caption: '专项/行业筛选后的去重客户',
    tag: 'Accounts',
    tone: 'blue',
  },
  {
    id: 'CMP-02',
    key: 'active_customers',
    label: '有互动行为客户数',
    value: formatNumber(kpiData.value.active_customers),
    caption: '至少匹配一条互动记录',
    tag: 'Active',
    tone: 'cyan',
  },
  {
    id: 'CMP-03',
    key: 'opportunity_count',
    label: '商机数',
    value: formatNumber(kpiData.value.opportunity_count),
    caption: '当前客户池内可追踪商机数量',
    tag: 'Oppty',
    tone: 'green',
  },
  {
    id: 'CMP-04',
    key: 'total_amount',
    label: '总金额',
    value: formatAmountYuan(kpiData.value.total_amount),
    caption: '在途商机金额汇总',
    tag: 'Amount',
    tone: 'blue',
  },
  {
    id: 'CMP-05',
    key: 'deal_customers',
    label: '对单客户',
    value: formatNumber(kpiData.value.deal_customers),
    caption: '已成交或已进入采购完成阶段',
    tag: 'Deal',
    tone: 'gold',
  },
])

const filterHint = computed(() => {
  const campaign = filters.campaign_tag || '全部专项'
  const start = filters.start_date || '-'
  const end = filters.end_date || '-'
  const industry = filters.industry || '全部行业'
  return `${campaign} ｜窗口 ${start} 至 ${end} ｜${industry} ｜样例客户 ${formatNumber(kpiData.value.total_customers)} 家`
})
const customerTotalPages = computed(() => Math.max(1, Number(customerData.value.total_pages || 1)))

function formatNumber(value, digits = 0) {
  const number = Number(value || 0)
  return number.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function formatAmountYuan(value) {
  const number = Number(value || 0)
  if (number >= 100000000) return `¥${formatNumber(number / 100000000, 2)}亿`
  if (number >= 10000) return `¥${formatNumber(number / 10000, 2)}万`
  return `¥${formatNumber(number, 2)}元`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

function channelLabel(value) {
  return channelLabels[value] || value || '未知渠道'
}

function queryParams(extra = {}) {
  const params = new URLSearchParams()
  Object.entries({ ...filters, ...extra }).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, value)
  })
  return params
}

async function fetchJson(path, extra) {
  const params = queryParams(extra)
  const response = await fetch(`${API_BASE}${path}?${params}`)
  if (!response.ok) throw new Error(`${path} failed`)
  return response.json()
}

async function fetchFilterOptions() {
  const response = await fetch(`${API_BASE}/filter-options`)
  if (!response.ok) return
  const options = await response.json()
  filterOptions.value = options
  if (!filters.campaign_tag && options.campaigns?.length) filters.campaign_tag = options.campaigns[0]
  if (!filters.start_date && options.min_date) filters.start_date = options.min_date
  if (!filters.end_date && options.max_date) filters.end_date = options.max_date
}

async function fetchCustomerData() {
  customerData.value = await fetchJson('/customers-by-stage', {
    ...customerFilters,
    page: customerPage.value,
    page_size: CUSTOMER_PAGE_SIZE,
  })
  customerPage.value = customerData.value.page || customerPage.value
}

async function fetchData() {
  loading.value = true
  try {
    const [
      kpis,
      opportunities,
      channels,
      stages,
      roles,
      signals,
      content,
    ] = await Promise.all([
      fetchJson('/kpis'),
      fetchJson('/funnel-distribution'),
      fetchJson('/channel-distribution'),
      fetchJson('/stage-distribution'),
      fetchJson('/role-coverage'),
      fetchJson('/tag-signals'),
      fetchJson('/content-effect'),
    ])
    kpiData.value = kpis
    opportunityData.value = opportunities
    channelData.value = channels
    stageData.value = stages
    roleData.value = roles
    tagData.value = signals
    contentData.value = content
    await fetchCustomerData()
  } finally {
    loading.value = false
  }
}

async function applyFilters() {
  customerFilters.stage = ''
  customerFilters.owner = ''
  customerFilters.keyword = ''
  customerPage.value = 1
  await fetchData()
}

async function applyCustomerFilters() {
  customerPage.value = 1
  await fetchCustomerData()
}

async function changeCustomerPage(page) {
  const nextPage = Math.min(Math.max(1, page), customerTotalPages.value)
  if (nextPage === customerPage.value) return
  customerPage.value = nextPage
  await fetchCustomerData()
}

function barWidth(value, list, field = 'count') {
  const max = Math.max(...(list || []).map(item => Number(item[field]) || 0), 0)
  if (!max) return '0%'
  return `${Math.max(4, (Number(value || 0) / max) * 100)}%`
}

function intentClass(level) {
  if (level === '高' || level === 'High') return 'high'
  if (level === '中' || level === 'Medium') return 'medium'
  return 'low'
}

function openCustomer(customer) {
  if (customer.id != null) router.push(`/customers/${customer.id}`)
}

onMounted(async () => {
  await fetchFilterOptions()
  await fetchData()
})
</script>

<template>
  <div class="campaign-board">
    <section class="panel filter-panel">
      <div class="panel-header">
        <div class="panel-meta">
          <b>筛选与观测窗口</b>
          <span class="panel-sub">专项、时间、渠道、行业口径联动</span>
        </div>
        <span class="panel-hint">{{ filterHint }}</span>
      </div>

      <div class="filter-grid">
        <label class="filter-field">
          <span>专项</span>
          <select v-model="filters.campaign_tag">
            <option value="">全部专项</option>
            <option v-for="campaign in filterOptions.campaigns" :key="campaign" :value="campaign">
              {{ campaign }}
            </option>
          </select>
        </label>
        <label class="filter-field range-field">
          <span>时间段</span>
          <div class="date-range">
            <input v-model="filters.start_date" type="date" />
            <em>至</em>
            <input v-model="filters.end_date" type="date" />
          </div>
        </label>
        <label class="filter-field">
          <span>渠道</span>
          <select v-model="filters.channel">
            <option value="">全部</option>
            <option v-for="channel in filterOptions.channels" :key="channel" :value="channel">
              {{ channelLabel(channel) }}
            </option>
          </select>
        </label>
        <label class="filter-field">
          <span>行业</span>
          <select v-model="filters.industry">
            <option value="">全部</option>
            <option v-for="industry in filterOptions.industries" :key="industry" :value="industry">
              {{ industry }}
            </option>
          </select>
        </label>
        <button class="primary-btn" type="button" :disabled="loading" @click="applyFilters">
          {{ loading ? '加载中' : '应用' }}
        </button>
      </div>

      <div class="kpi-grid">
        <article v-for="card in kpiCards" :key="card.key" class="kpi-card" :class="`tone-${card.tone}`">
          <div class="kpi-topline">
            <span class="kpi-id">{{ card.id }}</span>
            <span class="kpi-tag">{{ card.tag }}</span>
          </div>
          <div class="kpi-label">
            {{ card.label }}
            <FieldHelpTooltip :help="getCampaignHelp(card.key)" align="start" />
          </div>
          <strong class="kpi-value">{{ card.value }}</strong>
          <span class="kpi-caption">{{ card.caption }}</span>
        </article>
      </div>
    </section>

    <div class="grid-two">
      <section class="panel opportunity-panel">
        <div class="panel-header">
          <div class="panel-meta">
            <b>商机预测类别分布 <FieldHelpTooltip :help="getCampaignHelp('opportunity_distribution')" /></b>
            <span class="panel-sub">按预测类别聚合并区分状态</span>
          </div>
          <span class="panel-tag">Opportunity</span>
        </div>
        <div class="stack-list opportunity-list">
          <div v-for="item in opportunityData.categories" :key="item.forecast_type" class="stack-item">
            <div class="stack-row">
              <b>{{ item.forecast_type }}</b>
              <span>{{ item.count }} 客户 · {{ item.percentage }}%</span>
            </div>
            <div class="bar-track">
              <i :style="{ width: barWidth(item.count, opportunityData.categories) }"></i>
            </div>
            <div class="mini-stats">
              <span>在途 {{ item.active_count }}</span>
              <span>已下单 {{ item.deal_count }}</span>
            </div>
          </div>
          <div v-if="!opportunityData.categories?.length" class="empty-state">暂无数据</div>
        </div>
      </section>

      <section class="panel channel-panel">
        <div class="panel-header">
          <div class="panel-meta">
            <b>渠道归因 <FieldHelpTooltip :help="getCampaignHelp('channel_attribution')" /></b>
            <span class="panel-sub">按最近互动渠道归因</span>
          </div>
          <span class="panel-tag">Pie</span>
        </div>
        <div class="channel-layout">
          <div class="channel-ring">
            <div class="ring-core">
              <strong>{{ formatNumber(channelData.total) }}</strong>
              <span>客户</span>
            </div>
          </div>
          <div class="channel-list">
            <div v-for="item in channelData.channels" :key="item.channel" class="channel-item">
              <span>{{ channelLabel(item.channel) }}</span>
              <b>{{ item.percentage }}%</b>
              <em>{{ formatNumber(item.count) }} 家</em>
            </div>
            <div v-if="!channelData.channels?.length" class="empty-state">暂无数据</div>
          </div>
        </div>
      </section>
    </div>

    <div class="grid-three">
      <section class="panel signal-panel">
        <div class="panel-header">
          <div class="panel-meta">
            <b>采购阶段分布 <FieldHelpTooltip :help="getCampaignHelp('stage_distribution')" /></b>
            <span class="panel-sub">按 DWS 采购阶段聚合</span>
          </div>
          <span class="panel-tag">Stage</span>
        </div>
        <div class="compact-bars">
          <div v-for="item in stageData.stages" :key="item.stage" class="compact-bar">
            <span>{{ item.stage }}</span>
            <div class="bar-track"><i :style="{ width: barWidth(item.count, stageData.stages) }"></i></div>
            <b>{{ item.count }}</b>
          </div>
        </div>
      </section>

      <section class="panel signal-panel">
        <div class="panel-header">
          <div class="panel-meta">
            <b>关键角色覆盖 <FieldHelpTooltip :help="getCampaignHelp('role_coverage')" /></b>
            <span class="panel-sub">拍板者、决策者、评估者与采购推动者</span>
          </div>
          <span class="panel-tag">Persona</span>
        </div>
        <div class="compact-bars">
          <div v-for="item in roleData.roles" :key="item.role" class="compact-bar">
            <span>{{ item.role }}</span>
            <div class="bar-track"><i :style="{ width: barWidth(item.customer_count, roleData.roles, 'customer_count') }"></i></div>
            <b>{{ item.customer_count }}</b>
          </div>
        </div>
      </section>

      <section class="panel signal-panel">
        <div class="panel-header">
          <div class="panel-meta">
            <b>标签与痛点信号 <FieldHelpTooltip :help="getCampaignHelp('tag_signals')" /></b>
            <span class="panel-sub">按客户主表行业标签统计</span>
          </div>
          <span class="panel-tag">Tags</span>
        </div>
        <div class="compact-bars">
          <div v-for="item in tagData.signals" :key="`${item.type}-${item.signal}`" class="compact-bar">
            <span>{{ item.signal }}</span>
            <div class="bar-track"><i :style="{ width: barWidth(item.count, tagData.signals) }"></i></div>
            <b>{{ formatNumber(item.count) }} 家</b>
          </div>
          <div v-if="!tagData.signals?.length" class="empty-state">暂无信号</div>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-header">
        <div class="panel-meta">
          <b>内容效果 <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></b>
          <span class="panel-sub">打开、点击与漏斗贡献表现</span>
        </div>
        <span class="panel-tag">Content</span>
      </div>
      <div class="table-shell">
        <table>
          <thead>
            <tr>
              <th>内容</th>
              <th>类型</th>
              <th>适配角色</th>
              <th>内容兴趣 <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></th>
              <th>产品兴趣 <FieldHelpTooltip :help="getCampaignHelp('tag_signals')" /></th>
              <th>打开率 <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></th>
              <th>点击率 <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></th>
              <th>MQL <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></th>
              <th>SQL <FieldHelpTooltip :help="getCampaignHelp('content_effect')" /></th>
              <th>成交 <FieldHelpTooltip :help="getCampaignHelp('content_effect')" align="end" /></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in contentData.data" :key="item.content" class="content-effect-row">
              <td><b>{{ item.content }}</b></td>
              <td>{{ item.type }}</td>
              <td>{{ item.role }}</td>
              <td>{{ item.content_interest }}</td>
              <td>{{ item.product_interest || '-' }}</td>
              <td>{{ item.open_rate }}%</td>
              <td>{{ item.click_rate }}%</td>
              <td>{{ item.mql }}</td>
              <td>{{ item.sql }}</td>
              <td>{{ item.deal }}</td>
            </tr>
            <tr v-if="!contentData.data?.length">
              <td colspan="10" class="empty-state">暂无内容效果数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div class="panel-meta">
          <b>客户跟进 <FieldHelpTooltip :help="getCampaignHelp('customer_followup')" /></b>
          <span class="panel-sub">按阶段与负责人筛选推进动作</span>
        </div>
        <span class="panel-tag">Accounts</span>
      </div>
      <div class="follow-filter-grid">
        <label class="filter-field">
          <span>阶段</span>
          <select v-model="customerFilters.stage">
            <option value="">全部</option>
            <option v-for="stage in customerData.filter_options?.stages" :key="stage" :value="stage">
              {{ stage }}
            </option>
          </select>
        </label>
        <label class="filter-field">
          <span>负责人</span>
          <select v-model="customerFilters.owner">
            <option value="">全部</option>
            <option v-for="owner in customerData.filter_options?.owners" :key="owner" :value="owner">
              {{ owner }}
            </option>
          </select>
        </label>
        <label class="filter-field">
          <span>搜索客户</span>
          <input v-model.trim="customerFilters.keyword" type="search" placeholder="输入客户名称" />
        </label>
        <button class="secondary-btn" type="button" @click="applyCustomerFilters">应用筛选</button>
      </div>
      <div class="table-shell">
        <table>
          <thead>
            <tr>
              <th>客户 <FieldHelpTooltip :help="getCampaignHelp('abm_customer_name')" /></th>
              <th>客户标签 <FieldHelpTooltip :help="getCampaignHelp('customer_tags')" /></th>
              <th>采购阶段 <FieldHelpTooltip :help="getCampaignHelp('stage_distribution')" /></th>
              <th>关键人覆盖 <FieldHelpTooltip :help="getCampaignHelp('role_coverage')" /></th>
              <th>合作意向 <FieldHelpTooltip :help="getCampaignHelp('customer_followup')" /></th>
              <th>最近互动 <FieldHelpTooltip :help="getCampaignHelp('customer_followup')" /></th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="customer in customerData.flat"
              :key="customer.id || customer.customer_name"
              class="click-row"
              @click="openCustomer(customer)"
            >
              <td>
                <b>{{ customer.customer_name }}</b>
                <small>{{ customer.region || '-' }} · 来源 {{ customer.campaign_tag || '-' }}</small>
              </td>
              <td>
                <div class="tag-row">
                  <span v-for="tag in customer.tags?.slice(0, 4)" :key="tag">{{ tag }}</span>
                </div>
              </td>
              <td>{{ customer.stage }}</td>
              <td>{{ customer.role_coverage }}</td>
              <td>
                <span class="intent-pill" :class="intentClass(customer.intent_level)">
                  {{ customer.intent_level || '低' }} · {{ customer.intent_score || 0 }}分
                </span>
              </td>
              <td>
                <b>{{ formatDate(customer.last_interaction_time) }}</b>
                <small>{{ channelLabel(customer.last_interaction_channel) }}</small>
              </td>
              <td>{{ customer.followup_basis }}</td>
            </tr>
            <tr v-if="!customerData.flat?.length">
              <td colspan="7" class="empty-state">暂无符合条件的客户</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination-bar">
        <span>共 {{ formatNumber(customerData.total) }} 家客户</span>
        <div class="pagination-actions">
          <button
            class="secondary-btn"
            type="button"
            :disabled="customerPage <= 1"
            @click="changeCustomerPage(customerPage - 1)"
          >
            上一页
          </button>
          <b>第 {{ customerPage }} / {{ customerTotalPages }} 页</b>
          <button
            class="secondary-btn"
            type="button"
            :disabled="customerPage >= customerTotalPages"
            @click="changeCustomerPage(customerPage + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.campaign-board {
  display: grid;
  gap: 16px;
  color: var(--text);
}

.panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  box-shadow: 0 18px 48px rgba(0, 0, 0, .10);
}

.filter-panel {
  padding: 16px;
}

.panel:not(.filter-panel) {
  padding: 18px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.panel-meta {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.panel-meta b {
  color: var(--text);
  font-size: 15px;
}

.panel-sub,
.panel-hint {
  color: var(--muted);
  font-size: 12px;
}

.panel-hint {
  text-align: right;
}

.panel-tag,
.kpi-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(90, 167, 255, .24);
  border-radius: 999px;
  padding: 3px 10px;
  background: rgba(90, 167, 255, .10);
  color: var(--brand);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
  white-space: nowrap;
}

.filter-grid,
.follow-filter-grid {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(280px, 1.8fr) minmax(140px, .8fr) minmax(140px, .8fr) auto;
  gap: 12px;
  align-items: end;
}

.follow-filter-grid {
  grid-template-columns: minmax(160px, 1fr) minmax(160px, 1fr) minmax(260px, 2fr) auto;
  margin-bottom: 12px;
}

.filter-field {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.filter-field span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.filter-field input,
.filter-field select {
  width: 100%;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  padding: 0 11px;
  outline: none;
}

.date-range {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 8px;
  align-items: center;
}

.date-range em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.primary-btn,
.secondary-btn {
  height: 38px;
  border: 1px solid var(--brand);
  border-radius: 8px;
  padding: 0 18px;
  background: var(--brand);
  color: white;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.secondary-btn {
  background: rgba(90, 167, 255, .12);
  color: var(--brand);
}

.secondary-btn:disabled {
  border-color: var(--line);
  background: var(--surface);
  color: var(--muted);
  cursor: not-allowed;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.kpi-card {
  min-height: 140px;
  border: 1px solid rgba(90, 167, 255, .20);
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(255, 255, 255, .045), rgba(255, 255, 255, .018));
  padding: 14px;
}

.kpi-topline,
.stack-row,
.channel-item,
.compact-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.kpi-id {
  color: var(--muted);
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 11px;
  letter-spacing: .08em;
}

.kpi-label {
  display: flex;
  align-items: center;
  margin-top: 14px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.kpi-value {
  display: block;
  margin-top: 8px;
  color: var(--text);
  font-size: clamp(23px, 1.9vw, 29px);
  line-height: 1.05;
  overflow-wrap: anywhere;
}

.kpi-caption {
  display: block;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}

.grid-two {
  display: grid;
  align-items: stretch;
  grid-template-columns: minmax(0, 1.28fr) minmax(360px, .9fr);
  gap: 16px;
}

.grid-three {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.stack-list,
.compact-bars,
.channel-list {
  display: grid;
  gap: 12px;
}

.opportunity-panel,
.channel-panel {
  min-height: 300px;
}

.opportunity-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.stack-item {
  border: 1px solid rgba(90, 167, 255, .12);
  border-radius: 8px;
  background: var(--surface);
  padding: 12px;
}

.opportunity-list .stack-item {
  padding: 10px 12px;
}

.stack-row b,
.compact-bar span,
.channel-item span {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-row span,
.mini-stats,
.channel-item em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.bar-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(90, 167, 255, .10);
}

.stack-item .bar-track {
  margin: 8px 0 7px;
}

.bar-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #5aa7ff, #2dd4bf);
}

.mini-stats {
  display: flex;
  gap: 12px;
}

.channel-ring {
  display: grid;
  place-items: center;
  min-height: 0;
}

.channel-layout {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  min-height: 210px;
}

.ring-core {
  display: grid;
  place-items: center;
  width: 142px;
  height: 142px;
  border: 17px solid rgba(90, 167, 255, .20);
  border-top-color: #5aa7ff;
  border-right-color: #2dd4bf;
  border-radius: 999px;
}

.ring-core strong {
  color: var(--text);
  font-size: 22px;
  line-height: 1;
}

.ring-core span {
  color: var(--muted);
  font-size: 12px;
}

.channel-item {
  display: grid;
  grid-template-columns: minmax(72px, 1fr) 64px minmax(76px, auto);
  border: 1px solid rgba(90, 167, 255, .12);
  border-radius: 8px;
  background: var(--surface);
  padding: 10px 12px;
}

.channel-item b,
.compact-bar b {
  color: var(--brand);
  font-size: 13px;
  white-space: nowrap;
}

.compact-bar {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(100px, 1fr) 72px;
}

.signal-panel {
  min-height: 260px;
}

.signal-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.signal-cloud span,
.tag-row span,
.intent-pill {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(90, 167, 255, .18);
  border-radius: 999px;
  padding: 4px 9px;
  background: rgba(90, 167, 255, .09);
  color: var(--text);
  font-size: 12px;
}

.signal-cloud b {
  margin-left: 6px;
  color: var(--brand);
}

.table-shell {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1060px;
  border-collapse: collapse;
}

th,
td {
  border-bottom: 1px solid var(--line);
  padding: 11px 9px;
  text-align: left;
  vertical-align: top;
}

.content-effect-row td {
  padding-top: 15px;
  padding-bottom: 15px;
}

.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  color: var(--muted);
  font-size: 12px;
}

.pagination-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pagination-actions b {
  color: var(--text);
  font-size: 13px;
  white-space: nowrap;
}

th {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

td {
  color: var(--text);
  font-size: 13px;
}

td small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.intent-pill.high {
  color: #16a34a;
}

.intent-pill.medium {
  color: #ca8a04;
}

.intent-pill.low {
  color: #ef4444;
}

.click-row {
  cursor: pointer;
}

.click-row:hover {
  background: var(--surface-hover);
}

.empty-state {
  padding: 18px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 1280px) {
  .grid-two,
  .grid-three {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .filter-grid,
  .follow-filter-grid {
    grid-template-columns: 1fr;
  }

  .opportunity-list,
  .channel-layout {
    grid-template-columns: 1fr;
  }

  .date-range {
    grid-template-columns: 1fr;
  }

  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-header {
    flex-direction: column;
  }

  .panel-hint {
    text-align: left;
  }
}

@media (max-width: 620px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
