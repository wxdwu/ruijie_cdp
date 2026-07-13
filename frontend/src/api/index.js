import axios from 'axios'
import { BASE_URL } from '../config'

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (!axios.isCancel(err)) console.error('[API]', err)
    return Promise.reject(err)
  },
)

export const customerApi = {
  list: (params, config = {}) => http.get('/api/customers', { ...config, params }),
  get: (id) => http.get(`/api/customers/${id}`),
  contacts: (id) => http.get(`/api/customers/${id}/contacts`),
  interactions: (id, params) => http.get(`/api/customers/${id}/interactions`, { params }),
  opportunities: (id) => http.get(`/api/customers/${id}/opportunities`),
  aiInsight: (id) => http.get(`/api/customers/${id}/ai-insight`),
  statisticsByName: (customerName) => http.get('/api/customers/statistics/by-name', {
    params: { customer_name: customerName },
  }),
  filterOptions: (params = {}) => http.get('/api/customers/filter-options', { params }),
  export: (params) => http.get('/api/customers/export', { params, responseType: 'blob' }),
}

export const campaignApi = {
  filterOptions: () => http.get('/api/campaign/filter-options'),
  bootstrap: (params, config = {}) => http.get('/api/campaign/bootstrap', { ...config, params }),
  overview: (params, config = {}) => http.get('/api/campaign/overview', { ...config, params }),
  kpis: () => http.get('/api/campaign/kpis'),
  funnelDistribution: () => http.get('/api/campaign/funnel-distribution'),
  channelDistribution: (period = 'all') => http.get('/api/campaign/channel-distribution', {
    params: { period },
  }),
  roleCoverage: () => http.get('/api/campaign/role-coverage'),
  contentEffect: (period = 'all') => http.get('/api/campaign/content-effect', {
    params: { period },
  }),
  customersByStage: (params) => http.get('/api/campaign/customers-by-stage', { params }),
}

export const aiApi = {
  parse: (data) => http.post('/api/ai/parse', data),
  chat: (data) => http.post('/api/ai/chat', data),
  chatExport: (data) => http.post('/api/ai/chat/export', data, { responseType: 'blob' }),
}

export const reviewApi = {
  list: (params) => http.get('/api/review', { params }),
  stats: () => http.get('/api/review/stats'),
  approve: (id) => http.post(`/api/review/${id}/approve`),
  reject: (id) => http.post(`/api/review/${id}/reject`),
  batchApprove: (ids) => http.post('/api/review/batch-approve', { ids }),
  batchReject: (ids) => http.post('/api/review/batch-reject', { ids }),
  runDedup: () => http.post('/api/review/run-dedup'),
  dedupProgress: () => http.get('/api/review/dedup-progress'),
}

export const adminApi = {
  runEtl: () => http.post('/api/admin/etl/run'),
}

export default http
