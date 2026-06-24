import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { customerApi } from '../api'

export const useCustomerStore = defineStore('customer', () => {
  const list = ref([])
  const total = ref(0)
  const loading = ref(false)
  const current = ref(null)

  const filters = ref({
    keyword: '',
    industry: '',
    owner: '',
    owner_keyword: '',
    stage: '',
    intent_level: '',
    interaction_min: null,
    interaction_period: 30, // 默认30天
    channel: '',
    sort: '',
    page: 1,
    size: 20,
  })

  const totalPages = computed(() => Math.ceil(total.value / filters.value.size) || 1)

  async function fetchList() {
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

      const res = await customerApi.list(params)
      // Backend returns {items: [], total: N} or {items: [], total: N, ...}
      list.value = res.items ?? []
      total.value = res.total ?? list.value.length
    } catch (e) {
      console.error('fetchList', e)
      list.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
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
      industry: '',
      owner: '',
      owner_keyword: '',
      interaction_min: null,
      channel: '',
      stage: '',
      intent_level: '',
      sort: '',
      page: 1,
      size: 20,
    }
  }

  return {
    list, total, loading, current, filters, totalPages,
    fetchList, fetchDetail, setFilter, setFilters, setPage, reset,
  }
})
