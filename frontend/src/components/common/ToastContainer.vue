<script setup lang="ts">
import { ref } from "vue"
import { useToastState, useToast } from "../../composables/useToast"

// 全局单例 toast 队列（仅渲染，不涉及业务逻辑）
const state = useToastState()
const { remove } = useToast()

// 各类型对应的图标字符（圆形背景 + 颜色由样式控制）
const icons: Record<string, string> = {
  success: "✓",
  error: "✕",
  warning: "!",
  info: "i",
}

// 鼠标悬停时暂停自动关闭（主流 toast 行为，便于阅读），移开恢复
const hoveredId = ref<number | null>(null)

// 仅当“进度条”动画播放结束时触发关闭；避免其它动画事件冒泡误触
function onProgressEnd(id: number, e: AnimationEvent) {
  const target = e.target as HTMLElement | null
  if (target && target.dataset.role === "progress") {
    remove(id)
  }
}
</script>

<template>
  <div
    class="pointer-events-none fixed right-5 top-5 z-9999 flex w-88 max-w-[calc(100vw-2.5rem)] flex-col gap-2.5"
  >
    <transition-group name="toast">
      <div
        v-for="t in state.list"
        :key="t.id"
        class="toast-item pointer-events-auto overflow-hidden rounded-xl border bg-[rgba(30,30,46,0.96)] text-[#cdd6f4] shadow-2xl backdrop-blur-md"
        :class="{
          'border-emerald-500/50': t.type === 'success',
          'border-rose-500/50': t.type === 'error',
          'border-amber-500/50': t.type === 'warning',
          'border-sky-500/50': t.type === 'info',
        }"
        @mouseenter="hoveredId = t.id"
        @mouseleave="hoveredId = null"
      >
        <div class="flex items-start gap-3 p-3.5">
          <!-- 类型图标圆环 -->
          <span
            class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-sm font-bold leading-none"
            :class="{
              'bg-emerald-500/20 text-emerald-300': t.type === 'success',
              'bg-rose-500/20 text-rose-300': t.type === 'error',
              'bg-amber-500/20 text-amber-300': t.type === 'warning',
              'bg-sky-500/20 text-sky-300': t.type === 'info',
            }"
          >
            {{ icons[t.type] }}
          </span>
          <!-- 标题 + 可选详情 -->
          <div class="min-w-0 flex-1">
            <div class="text-sm font-semibold leading-snug wrap-break-word">
              {{ t.title }}
            </div>
            <div
              v-if="t.detail"
              class="mt-1 whitespace-pre-wrap wrap-break-word text-xs leading-relaxed opacity-80"
            >
              {{ t.detail }}
            </div>
          </div>
          <!-- 关闭按钮 -->
          <button
            class="shrink-0 text-lg leading-none opacity-40 transition hover:opacity-100"
            aria-label="关闭"
            @click="remove(t.id)"
          >
            ×
          </button>
        </div>
        <!-- 自动关闭进度条（动画结束时由组件关闭该 toast） -->
        <div
          v-if="t.duration > 0"
          class="toast-progress h-1 w-full"
          :class="{
            'bg-emerald-400': t.type === 'success',
            'bg-rose-400': t.type === 'error',
            'bg-amber-400': t.type === 'warning',
            'bg-sky-400': t.type === 'info',
          }"
          :style="{
            animationDuration: t.duration + 'ms',
            animationPlayState: hoveredId === t.id ? 'paused' : 'running',
          }"
          data-role="progress"
          @animationend="onProgressEnd(t.id, $event)"
        ></div>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
/* 进度条收缩动画：随时间从满到空，配合 duration 自动关闭 */
.toast-progress {
  transform-origin: left center;
  animation-name: toast-progress;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}

@keyframes toast-progress {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

/* 进入：右滑 + 轻微上移 + 缩放 */
.toast-enter-active {
  transition: all 0.32s cubic-bezier(0.21, 1.02, 0.73, 1);
}
.toast-leave-active {
  transition: all 0.25s ease;
  position: absolute;
  right: 0;
  width: 100%;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(24px) scale(0.96);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(24px) scale(0.96);
}
</style>
