import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    console.error('[API]', err)
    return Promise.reject(err)
  },
)

export const customerApi = {
  list: (params) => http.get('/customers', { params }),
  get: (id) => http.get(`/customers/${id}`),
  contacts: (id) => http.get(`/customers/${id}/contacts`),
  interactions: (id, params) => http.get(`/customers/${id}/interactions`, { params }),
  opportunities: (id) => http.get(`/customers/${id}/opportunities`),
  aiInsight: (id) => http.get(`/customers/${id}/ai-insight`),
  priorityContact: (id) => http.get(`/customers/${id}/priority-contact`),
  statisticsByName: (customerName) => http.get('/customers/statistics/by-name', {
    params: { customer_name: customerName },
  }),
  filterOptions: () => http.get('/customers/filter-options'),
  export: (params) => http.get('/customers/export', { params, responseType: 'blob' }),
}

export const campaignApi = {
  kpis: () => http.get('/campaign/kpis'),
  funnelDistribution: () => http.get('/campaign/funnel-distribution'),
  channelDistribution: (period = 'all') => http.get('/campaign/channel-distribution', {
    params: { period },
  }),
  roleCoverage: () => http.get('/campaign/role-coverage'),
  contentEffect: (period = 'all') => http.get('/campaign/content-effect', {
    params: { period },
  }),
  customersByStage: () => http.get('/campaign/customers-by-stage'),
}

export const aiApi = {
  parse: (data) => http.post('/ai/parse', data),
  chat: (data) => http.post('/ai/chat', data),
  chatExport: (data) => http.post('/ai/chat/export', data, { responseType: 'blob' }),
}

export const reviewApi = {
  list: (params) => http.get('/review', { params }),
  stats: () => http.get('/review/stats'),
  approve: (id) => http.post(`/review/${id}/approve`),
  reject: (id) => http.post(`/review/${id}/reject`),
  batchApprove: (ids) => http.post('/review/batch-approve', { ids }),
  batchReject: (ids) => http.post('/review/batch-reject', { ids }),
  runDedup: () => http.post('/review/run-dedup'),
  dedupProgress: () => http.get('/review/dedup-progress'),
}

export const adminApi = {
  runEtl: () => http.post('/admin/etl/run'),
}

export default http
