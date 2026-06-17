<script setup>
defineProps({
  // 推荐联系人列表，每个元素包含 contact_name, role_category, department, reason, relevance_score 等
  recommendations: {
    type: Array,
    default: () => [],
  },
  // 数据来源标记，用于显示 AI 或规则模式
  source: {
    type: String,
    default: "rule",
  },
})
</script>

<template>
  <div class="rounded-xl border border-[var(--brand)]/30 bg-[var(--brand)]/5 p-5">
    <!-- 标题行 -->
    <div class="flex items-center gap-2 mb-4">
      <span class="text-lg">🤖</span>
      <span class="text-sm font-medium text-[var(--brand)]">AI 推荐优先联系人</span>
      <span
        v-if="source === 'ai'"
        class="text-xs px-2 py-0.5 rounded-full bg-[var(--brand)]/20 text-[var(--brand)]"
      >
        AI 分析
      </span>
      <span
        v-else
        class="text-xs px-2 py-0.5 rounded-full bg-[var(--muted)]/15 text-[var(--muted)]"
      >
        规则评分
      </span>
    </div>

    <!-- 推荐列表 -->
    <div v-if="recommendations && recommendations.length > 0" class="space-y-3">
      <div
        v-for="(contact, idx) in recommendations"
        :key="idx"
        class="flex items-start gap-4 rounded-lg bg-white/5 p-3 hover:bg-white/10 transition-colors"
      >
        <!-- 排名标识 -->
        <div
          class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
          :class="
            idx === 0
              ? 'bg-[var(--brand)] text-white'
              : 'bg-[var(--muted)]/20 text-[var(--text)]'
          "
        >
          {{ idx + 1 }}
        </div>

        <!-- 联系人信息 -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-medium text-[var(--text)]">
              {{ contact.contact_name || "未命名" }}
            </span>
            <span
              v-if="contact.role_category"
              class="inline-flex items-center rounded-full border border-[var(--brand)]/30 bg-[var(--brand)]/10 px-2 py-0 text-xs text-[var(--brand)]"
            >
              {{ contact.role_category }}
            </span>
          </div>

          <div class="text-xs text-[var(--muted)] mb-1">
            {{ contact.department || "" }}{{ contact.department && contact.position ? " · " : "" }}{{ contact.position || "" }}
          </div>

          <!-- 电话和邮箱 -->
          <div v-if="contact.mobile || contact.email" class="text-xs text-[var(--muted)] mb-1.5 flex items-center gap-3">
            <span v-if="contact.mobile" class="flex items-center gap-1">
              <span class="text-[var(--brand)]">📞</span>
              {{ contact.mobile }}
            </span>
            <span v-if="contact.email" class="flex items-center gap-1">
              <span class="text-[var(--brand)]">✉️</span>
              {{ contact.email }}
            </span>
          </div>

          <!-- 推荐理由 -->
          <div class="text-xs text-[var(--muted)] bg-[var(--brand)]/5 rounded-lg px-3 py-2 leading-relaxed">
            💡 {{ contact.reason }}
          </div>
        </div>

        <!-- 相关性分数 -->
        <div class="flex-shrink-0 text-right">
          <div class="text-lg font-semibold text-[var(--brand)]">
            {{ contact.relevance_score || "-" }}
          </div>
          <div class="text-[10px] text-[var(--muted)]">相关性</div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="text-sm text-[var(--muted)] text-center py-4">
      暂无联系人
    </div>
  </div>
</template>
