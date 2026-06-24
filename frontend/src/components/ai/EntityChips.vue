<template>
  <div class="entity-chips">
    <span
      v-for="(value, key) in displayEntities"
      :key="key"
      :class="['chip', `chip-${key}`]"
    >
      <span class="chip-label">{{ getLabel(key) }}:</span>
      <span class="chip-value">{{ value }}</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  entities: Record<string, any>
}>()

const displayEntities = computed(() => {
  const result: Record<string, any> = {}
  const allowedKeys = ['industry', 'region', 'stage', 'intent_level', 'channel', 'keyword', 'interaction_min', 'owner_name', 'customer_name', 'contact_count_min', 'active_opp_count_min']
  for (const key of allowedKeys) {
    if (props.entities[key] !== undefined && props.entities[key] !== null) {
      result[key] = props.entities[key]
    }
  }
  return result
})

const labels: Record<string, string> = {
  industry: '行业',
  region: '区域',
  stage: '阶段',
  intent_level: '意向',
  channel: '渠道',
  keyword: '关键词',
  interaction_min: '互动≥',
  owner_name: '负责人',
  customer_name: '客户名称',
  contact_count_min: '联系人≥',
  active_opp_count_min: '商机数≥',
}

function getLabel(key: string): string {
  return labels[key] || key
}
</script>

<style scoped>
.entity-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
}

.chip-label {
  color: var(--muted);
  font-weight: 500;
}

.chip-value {
  color: var(--text);
  font-weight: 600;
}

.chip-industry {
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.3);
}

.chip-region {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
}

.chip-stage {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.3);
}

.chip-intent_level {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
}

.chip-channel {
  background: rgba(139, 92, 246, 0.1);
  border-color: rgba(139, 92, 246, 0.3);
}

.chip-keyword {
  background: rgba(236, 72, 153, 0.1);
  border-color: rgba(236, 72, 153, 0.3);
}

.chip-interaction_min {
  background: rgba(20, 184, 166, 0.1);
  border-color: rgba(20, 184, 166, 0.3);
}

.chip-owner_name {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.3);
}

.chip-customer_name {
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.3);
}

.chip-contact_count_min {
  background: rgba(139, 92, 246, 0.1);
  border-color: rgba(139, 92, 246, 0.3);
}

.chip-active_opp_count_min {
  background: rgba(236, 72, 153, 0.1);
  border-color: rgba(236, 72, 153, 0.3);
}
</style>
