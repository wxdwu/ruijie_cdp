<script setup>
import { ref } from 'vue'
import { customerApi } from '../../api'

const props = defineProps({
  filters: {
    type: Object,
    default: () => ({}),
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  disabledReason: {
    type: String,
    default: '',
  },
})

const exporting = ref(false)

async function handleExport() {
  if (exporting.value || props.disabled) return

  exporting.value = true
  try {
    const blob = await customerApi.export(props.filters)

    // Create download link
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `客户列表_${new Date().toISOString().slice(0, 10)}.xlsx`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Export failed:', e)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <button
    @click="handleExport"
    :disabled="exporting || disabled"
    :title="disabled ? disabledReason : ''"
    class="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-white/5 px-4 py-2 text-sm font-medium text-[var(--text)] transition-colors hover:bg-white/10 disabled:opacity-50"
  >
    <span>{{ exporting ? '⏳' : '📥' }}</span>
    {{ exporting ? '导出中...' : (disabled ? '暂不支持导出' : '导出数据') }}
  </button>
</template>
