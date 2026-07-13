import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { customerApi } from '../api'

export const useCustomerStore = defineStore('customer', () => {
  const list = ref([])
  const total = ref(0)
  const loading = ref(false)
  const current = ref(null)
  let listRequestId = 0
  let listAbortController = null

  const filters = ref({
    keyword: '',
    special_project: '企业彩光ICT',
    industry: '',
    region: '',
    region_keyword: '',
    owner: '',
    owner_keyword: '',
    stage: '',
    intent_level: '',
    interaction_min: null,
    interaction_period: 30, // 默认30天
    attribute: '',
    channel: '',
    sort: '',
    page: 1,
    size: 20,
  })

  const totalPages = computed(() => Math.ceil(total.value / filters.value.size) || 1)
  const isKeyAccountMode = computed(() => filters.value.special_project === '重客')

  async function fetchList() {
    const requestId = ++listRequestId
    listAbortController?.abort()
    const abortController = new AbortController()
    listAbortController = abortController
    loading.value = true
    try {
      // Build params - remove null/empty values
      const params = {}
      Object.entries(filters.value).forEach(([key, value]) => {
        if (value !== null && value !== '' && value !== undefined) {
          params[key] = value
        }
      })
      // Map frontend params to backend param names
      if (params.size) params.size = params.size

      const res = await customerApi.list(params, { signal: abortController.signal })
      if (requestId !== listRequestId) return
      // Backend returns {items: [], total: N} or {items: [], total: N, ...}
      list.value = res.items ?? []
      total.value = res.total ?? list.value.length
    } catch (e) {
      if (requestId !== listRequestId || abortController.signal.aborted) return
      console.error('fetchList', e)
      list.value = []
      total.value = 0
    } finally {
      if (requestId === listRequestId) {
        listAbortController = null
        loading.value = false
      }
    }
  }

  function cancelListRequest() {
    listRequestId += 1
    listAbortController?.abort()
    listAbortController = null
    loading.value = false
  }

  async function fetchDetail(id) {
    loading.value = true
    try {
      current.value = await customerApi.get(id)
    } catch (e) {
      console.error('fetchDetail', e)
      current.value = null
    } finally {
      loading.value = false
    }
  }

  function setFilter(key, value) {
    filters.value[key] = value
    if (key !== 'page') filters.value.page = 1
  }

  function setFilters(newFilters) {
    Object.assign(filters.value, newFilters)
    filters.value.page = 1
  }

  function setPage(p) {
    filters.value.page = p
  }

  function reset() {
    filters.value = {
      keyword: '',
      special_project: '企业彩光ICT',
      industry: '',
      region: '',
      region_keyword: '',
      owner: '',
      owner_keyword: '',
      interaction_min: null,
      interaction_period: 30,
      attribute: '',
      channel: '',
      stage: '',
      intent_level: '',
      sort: '',
      page: 1,
      size: 20,
    }
  }

  return {
    list, total, loading, current, filters, totalPages, isKeyAccountMode,
    fetchList, cancelListRequest, fetchDetail, setFilter, setFilters, setPage, reset,
  }
})
