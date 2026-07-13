<script setup>
import { onBeforeUnmount, onMounted, watch, ref } from 'vue'
import { useCustomerStore } from '../stores/customer'
import FilterBar from '../components/customer/FilterBar.vue'
import CustomerTable from '../components/customer/CustomerTable.vue'

const store = useCustomerStore()
const pageInput = ref('')

function handleApplyFilters(filters) {
  store.setFilters(filters)
  store.fetchList()
}

function handlePageChange(page) {
  if (page < 1 || page > store.totalPages) return
  store.setPage(page)
  store.fetchList()
}

function goToPage() {
  const p = parseInt(pageInput.value)
  if (p >= 1 && p <= store.totalPages) {
    handlePageChange(p)
    pageInput.value = ''
  }
}

// Compute visible pages: 1, 2, 3, ..., last
function getVisiblePages() {
  const pages = []
  const total = store.totalPages
  const current = store.filters.page
  const maxVisible = 3

  pages.push(1)
  if (current > 3) pages.push('...')
  for (let p = 2; p <= Math.min(maxVisible, total); p++) {
    if (p !== current || current <= maxVisible) pages.push(p)
  }
  if (current > maxVisible) pages.push(current)
  if (total > maxVisible + 1 && current < total) pages.push('...')
  if (total > maxVisible) pages.push(total)

  return [...new Set(pages)]
}

watch(() => store.filters.page, () => {
  // Reactive update
})

onMounted(() => {
  store.fetchList()
})

onBeforeUnmount(() => {
  store.cancelListRequest()
})
</script>

<template>
  <div class="flex flex-col gap-5 p-6">
    <!-- Page Header -->
    <div>
      <div>
        <h1 class="text-xl font-semibold text-[var(--text)]">客户列表</h1>
        <p class="text-sm text-[var(--muted)]">共 {{ store.total }} 条记录，{{ store.totalPages }} 页</p>
      </div>
    </div>

    <!-- Filter Bar -->
    <FilterBar @apply="handleApplyFilters" />

    <!-- Customer Table -->
    <CustomerTable
      :customers="store.list"
      :loading="store.loading"
      :key-account-mode="store.isKeyAccountMode"
    />

    <!-- Pagination -->
    <div v-if="store.totalPages > 1" class="flex items-center justify-center gap-3">
      <button
        @click="handlePageChange(store.filters.page - 1)"
        :disabled="store.filters.page <= 1"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        上一页
      </button>

      <div class="flex items-center gap-1">
        <button
          v-for="(p, i) in getVisiblePages()"
          :key="i"
          @click="typeof p === 'number' ? handlePageChange(p) : null"
          :disabled="p === '...'"
          class="h-9 w-9 rounded-lg text-sm transition-colors"
          :class="
            p === '...'
              ? 'border-none text-[var(--muted)] cursor-default'
              : store.filters.page === p
              ? 'bg-[var(--brand)] text-white'
              : 'border border-[var(--line)] bg-white/5 text-[var(--text)] hover:bg-white/10'
          "
        >
          {{ p }}
        </button>
      </div>

      <button
        @click="handlePageChange(store.filters.page + 1)"
        :disabled="store.filters.page >= store.totalPages"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        下一页
      </button>

      <div class="flex items-center gap-2 ml-4">
        <input
          v-model="pageInput"
          @keyup.enter="goToPage"
          type="number"
          :min="1"
          :max="store.totalPages"
          placeholder="页码"
          class="w-16 rounded-lg border border-[var(--line)] bg-white/5 px-2 py-1.5 text-sm text-center text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--brand)] focus:outline-none"
        />
        <button
          @click="goToPage"
          class="rounded-lg border border-[var(--line)] bg-white/5 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/10"
        >
          跳转
        </button>
      </div>
    </div>
  </div>
</template>
