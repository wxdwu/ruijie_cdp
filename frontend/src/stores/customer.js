import { defineStore } from "pinia"
import { ref, computed } from "vue"
import { customerApi } from "../api"

const PAGE_SIZE = 20

const ALLOWED_SORT_FIELDS = [
  "customer_name",
  "industry",
  "intent_score",
  "interaction_count_30d",
  "interaction_count_total",
  "last_interaction_time",
  "active_opp_amount",
  "won_amount",
  "updated_at",
]

export const useCustomerStore = defineStore("customer", () => {
  const list = ref([])
  const total = ref(0)
  const allItems = ref([])
  const loading = ref(false)
  const current = ref(null)
  let listRequestId = 0
  let listAbortController = null

  const filters = ref({
    keyword: [],
    special_project: ["企业彩光ICT"],
    industry: [],
    region: [],
    region_keyword: "",
    owner: [],
    owner_keyword: "",
    stage: "",
    intent_level: "",
    interaction_min: null,
    interaction_period: 30, // 默认30天
    attribute: "",
    channel: [],
    sort: "",
    page: 1,
    size: PAGE_SIZE,
  })

  const totalPages = computed(() => Math.ceil(total.value / filters.value.size) || 1)
  const isKeyAccountMode = computed(() => (
    filters.value.special_project.length === 1 && filters.value.special_project[0] === "重客"
  ))

  function normalizeArray(value) {
    if (Array.isArray(value)) return value
    if (value === "" || value === null || value === undefined) return []
    return [value]
  }

  async function fetchList() {
    const requestId = ++listRequestId
    listAbortController?.abort()
    const abortController = new AbortController()
    listAbortController = abortController
    loading.value = true

    const f = filters.value
    // 多选维度直接以数组形式传给后端，由后端做 IN 过滤与服务端分页
    const params = {
      keyword: f.keyword || undefined,
      special_project: f.special_project,
      industry: f.industry,
      region: f.region,
      owner: f.owner,
      channel: f.channel,
      interaction_min: f.interaction_min,
      interaction_period: f.interaction_period,
      attribute: f.attribute || undefined,
      stage: f.stage || undefined,
      intent_level: f.intent_level || undefined,
      sort: f.sort || undefined,
      page: f.page,
      size: f.size,
    }

    try {
      const res = await customerApi.list(params, { signal: abortController.signal })
      if (requestId !== listRequestId) return
      list.value = res.items ?? []
      total.value = res.total ?? 0
      allItems.value = res.items ?? []
    } catch (e) {
      if (requestId !== listRequestId || abortController.signal.aborted) return
      console.error("fetchList", e)
      list.value = []
      total.value = 0
      allItems.value = []
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
      console.error("fetchDetail", e)
      current.value = null
    } finally {
      loading.value = false
    }
  }

  function setFilter(key, value) {
    filters.value[key] = value
    if (key !== "page") filters.value.page = 1
  }

  function setFilters(newFilters) {
    Object.assign(filters.value, newFilters)
    // 确保数组类筛选字段为数组
    filters.value.special_project = normalizeArray(filters.value.special_project)
    filters.value.industry = normalizeArray(filters.value.industry)
    filters.value.region = normalizeArray(filters.value.region)
    filters.value.owner = normalizeArray(filters.value.owner)
    filters.value.keyword = normalizeArray(filters.value.keyword)
    filters.value.channel = normalizeArray(filters.value.channel)
    filters.value.page = 1
  }

  function setPage(p) {
    filters.value.page = p
  }

  function reset() {
    filters.value = {
      keyword: [],
      special_project: ["企业彩光ICT"],
      industry: [],
      region: [],
      region_keyword: "",
      owner: [],
      owner_keyword: "",
      interaction_min: null,
      interaction_period: 30,
      attribute: "",
      channel: [],
      stage: "",
      intent_level: "",
      sort: "",
      page: 1,
      size: PAGE_SIZE,
    }
  }

  return {
    list, total, allItems, loading, current, filters, totalPages, isKeyAccountMode,
    fetchList, cancelListRequest, fetchDetail, setFilter, setFilters, setPage, reset,
  }
})
