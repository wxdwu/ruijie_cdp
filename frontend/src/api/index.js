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
  events: (id) => http.get(`/customers/${id}/events`),
  tags: (id) => http.get(`/customers/${id}/tags`),
  update: (id, data) => http.put(`/customers/${id}`, data),
  filterOptions: () => http.get('/customers/filter-options'),
  export: (params) => http.get('/customers/export', { params, responseType: 'blob' }),
}

export const campaignApi = {
  list: (params) => http.get('/campaigns', { params }),
  get: (id) => http.get(`/campaigns/${id}`),
  create: (data) => http.post('/campaigns', data),
  update: (id, data) => http.put(`/campaigns/${id}`, data),
  launch: (id) => http.post(`/campaigns/${id}/launch`),
}

export const aiApi = {
  chat: (data) => http.post('/ai/chat', data),
  summary: (customerId) => http.get(`/ai/summary/${customerId}`),
  suggest: (data) => http.post('/ai/suggest', data),
}

export const reviewApi = {
  list: (params) => http.get('/reviews', { params }),
  approve: (id) => http.post(`/reviews/${id}/approve`),
  reject: (id, data) => http.post(`/reviews/${id}/reject`, data),
}

export const exportApi = {
  customers: (params) => http.get('/export/customers', { params, responseType: 'blob' }),
  campaign: (id) => http.get(`/export/campaigns/${id}`, { responseType: 'blob' }),
}

export default http
