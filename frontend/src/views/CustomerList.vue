<script setup>
import { onMounted, watch } from 'vue'
import { useCustomerStore } from '../stores/customer'
import FilterBar from '../components/customer/FilterBar.vue'
import CustomerTable from '../components/customer/CustomerTable.vue'
import ExportButton from '../components/customer/ExportButton.vue'

const store = useCustomerStore()

function handleApplyFilters(filters) {
  store.setFilters(filters)
  store.fetchList()
}

function handlePageChange(page) {
  store.setPage(page)
  store.fetchList()
}

// Watch for page changes in store
watch(() => store.filters.page, () => {
  // Reactive update
})

onMounted(() => {
  store.fetchList()
})
</script>

<template>
  <div class="flex flex-col gap-5 p-6">
    <!-- Page Header with Export -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold text-[var(--text)]">客户列表</h1>
        <p class="text-sm text-[var(--muted)]">共 {{ store.total }} 条记录</p>
      </div>
      <ExportButton :filters="store.filters" />
    </div>

    <!-- Filter Bar -->
    <FilterBar @apply="handleApplyFilters" />

    <!-- Customer Table -->
    <CustomerTable :customers="store.list" :loading="store.loading" />

    <!-- Pagination -->
    <div v-if="store.totalPages > 1" class="flex items-center justify-center gap-2">
      <button
        @click="handlePageChange(store.filters.page - 1)"
        :disabled="store.filters.page <= 1"
        class="rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        上一页
      </button>

      <div class="flex items-center gap-1">
        <button
          v-for="p in store.totalPages"
          :key="p"
          @click="handlePageChange(p)"
          class="h-9 w-9 rounded-lg text-sm transition-colors"
          :class="
            store.filters.page === p
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
    </div>
  </div>
</template>
