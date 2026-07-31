<script setup lang="ts">
import { useToastState, useToast } from "../../composables/useToast"

const state = useToastState()
const { remove } = useToast()

const icons: Record<string, string> = {
  success: "✓",
  error: "✕",
  warning: "!",
  info: "i",
}
</script>

<template>
  <div class="pointer-events-none fixed right-4 top-4 z-[9999] flex w-80 flex-col gap-2">
    <transition-group name="toast">
      <div
        v-for="t in state.list"
        :key="t.id"
        class="pointer-events-auto rounded-lg border px-4 py-3 shadow-lg backdrop-blur"
        :class="{
          'border-emerald-500/40 bg-emerald-500/10 text-emerald-200': t.type === 'success',
          'border-rose-500/40 bg-rose-500/10 text-rose-200': t.type === 'error',
          'border-amber-500/40 bg-amber-500/10 text-amber-200': t.type === 'warning',
          'border-sky-500/40 bg-sky-500/10 text-sky-200': t.type === 'info',
        }"
      >
        <div class="flex items-start gap-2">
          <span class="mt-0.5 font-bold leading-none">{{ icons[t.type] }}</span>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium break-words">{{ t.title }}</div>
            <div
              v-if="t.detail"
              class="mt-1 whitespace-pre-wrap break-words text-xs opacity-80"
            >
              {{ t.detail }}
            </div>
          </div>
          <button
            class="ml-1 leading-none opacity-60 transition hover:opacity-100"
            aria-label="关闭"
            @click="remove(t.id)"
          >
            ×
          </button>
        </div>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(16px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
