<script setup>
defineProps({
  intent: { type: String, default: '-' },
  interactionCount: { type: Number, default: 0 },
  stage: { type: String, default: '-' },
  keyRoles: { type: String, default: '-' },
  opportunityCount: { type: Number, default: 0 },
})

const intentColors = {
  '高': 'bg-green-500/20 text-green-400 border-green-500/30',
  '中': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '低': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

const stageColors = {
  '问题识别': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  '解决方案探索': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  '需求构建': 'bg-green-500/20 text-green-400 border-green-500/30',
}
</script>

<template>
  <div class="grid grid-cols-5 gap-4">
    <!-- 合作意向 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">合作意向</div>
      <div class="text-2xl font-bold text-[var(--text)]">
        <span
          v-if="intent !== '-'"
          class="inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium"
          :class="intentColors[intent] || intentColors['低']"
        >
          {{ intent }}
        </span>
        <span v-else class="text-[var(--muted)]">-</span>
      </div>
    </div>

    <!-- 近30天互动 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">近30天互动</div>
      <div class="text-2xl font-bold text-[var(--text)]">{{ interactionCount }}</div>
      <div class="text-xs text-[var(--muted)] mt-1">次</div>
    </div>

    <!-- 采购阶段 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">采购阶段</div>
      <div class="text-lg font-bold text-[var(--text)]">
        <span
          v-if="stage !== '-'"
          class="inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium"
          :class="stageColors[stage] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'"
        >
          {{ stage }}
        </span>
        <span v-else class="text-[var(--muted)]">-</span>
      </div>
    </div>

    <!-- 关键角色覆盖 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">关键角色覆盖</div>
      <div class="text-2xl font-bold text-[var(--text)]">{{ keyRoles }}</div>
      <div class="text-xs text-[var(--muted)] mt-1">人</div>
    </div>

    <!-- 在途商机 -->
    <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <div class="text-xs text-[var(--muted)] mb-2">在途商机</div>
      <div class="text-2xl font-bold text-[var(--text)]">{{ opportunityCount }}</div>
      <div class="text-xs text-[var(--muted)] mt-1">个</div>
    </div>
  </div>
</template>
