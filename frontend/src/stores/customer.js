import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { customerApi } from '../api'

export const useCustomerStore = defineStore('customer', () => {
  const list = ref([])
  const total = ref(0)
  const loading = ref(false)
  const current = ref(null)

  const filters = ref({
    specialProject: '企业彩光ICT',
    keyword: '',
    industry: '',
    owner: '',
    interactionCount: null,
    interactionType: '',
    page: 1,
    pageSize: 20,
  })

  const totalPages = computed(() => Math.ceil(total.value / filters.value.pageSize) || 1)

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

      const res = await customerApi.list(params)
      list.value = res.items ?? res.data ?? []
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
      specialProject: '企业彩光ICT',
      keyword: '',
      industry: '',
      owner: '',
      interactionCount: null,
      interactionType: '',
      page: 1,
      pageSize: 20,
    }
  }

  return {
    list, total, loading, current, filters, totalPages,
    fetchList, fetchDetail, setFilter, setFilters, setPage, reset,
  }
})
