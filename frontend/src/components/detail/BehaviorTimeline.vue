<script setup>
import { computed } from 'vue'
import FieldHelpTooltip from '../customer/FieldHelpTooltip.vue'

const props = defineProps({
  interactions: { type: Array, default: () => [] },
})

const displayedInteractions = computed(() => (props.interactions || []).slice(0, 18))

const help = {
  title: '近期互动',
  type: 'src',
  meaning: '客户 360 概览中的近期互动时间轴卡片。',
  sourceTables: 'dws_interaction_detail',
  sourceFields: 'dws_interaction_detail.event_time, dws_interaction_detail.source_table, dws_interaction_detail.channel, dws_interaction_detail.behavior_type, dws_interaction_detail.contact_name, dws_interaction_detail.mobile, dws_interaction_detail.content, dws_interaction_detail.is_high_value, dws_interaction_detail.source_id',
  fields: [
    {
      type: 'src',
      variable: 'event_time',
      meaning: '行为发生时间',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'event_time(行为发生时间)',
      calculation: '按 event_time 倒序展示最近 18 条互动。',
      emptyState: '缺失时显示 -。',
    },
    {
      type: 'src',
      variable: 'source_table',
      meaning: '来源系统',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'source_table(来源表)',
      calculation: '直接展示来源系统标识，如 linkflow、zhique、tianrun。',
      emptyState: '缺失时显示未知来源。',
    },
    {
      type: 'src',
      variable: 'channel',
      meaning: '渠道分类',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'channel(渠道分类)',
      calculation: '前端将 web/email/wechat/event 映射为官网/邮件/微信/直播活动。',
      emptyState: '缺失时显示其他。',
    },
    {
      type: 'src',
      variable: 'behavior_type',
      meaning: '原始行为类型',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'behavior_type(原始行为类型)',
      calculation: '用于行为类型标签和底部摘要，如 WEBSITE__PAGE_VIEW。',
      emptyState: '缺失时显示互动事件。',
    },
    {
      type: 'src',
      variable: 'contact_name',
      meaning: '发生互动的联系人',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'contact_name(联系人姓名)',
      calculation: '直接展示互动记录关联联系人。',
      emptyState: '缺失时显示未识别联系人。',
    },
    {
      type: 'src',
      variable: 'mobile',
      meaning: '互动记录关联手机号',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'mobile(手机号)',
      calculation: '当前不作为主展示字段，用于追溯和联系人匹配。',
      emptyState: '缺失时不展示。',
    },
    {
      type: 'src',
      variable: 'content',
      meaning: '行为内容或标题',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'content(行为内容/标题)',
      calculation: '四格中的互动内容优先使用 content，缺失时回退 behavior_type。',
      emptyState: '缺失时显示行为类型或无互动内容。',
    },
    {
      type: 'src',
      variable: 'is_high_value',
      meaning: '是否高价值行为',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'is_high_value(是否高价值行为)',
      calculation: '当前不主展示，可作为后续高价值标签扩展。',
      emptyState: '缺失时按非高价值处理。',
    },
    {
      type: 'src',
      variable: 'source_id',
      meaning: '源表主键 ID',
      sourceTable: 'dws_interaction_detail',
      sourceFieldDisplay: 'source_id(源表主键ID)',
      calculation: '用于去重和追溯，不在时间线卡片主展示。',
      emptyState: '缺失时不展示。',
    },
  ],
  calculation: '后端按当前客户名称查询 dws_interaction_detail，ORDER BY event_time DESC，前端展示最近 18 条。',
  emptyState: '没有互动记录时显示暂无互动记录。',
}

function toDate(dt) {
  if (!dt) return null
  const date = new Date(dt)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatFullTime(dt) {
  const date = toDate(dt)
  if (!date) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatStampDate(dt) {
  const date = toDate(dt)
  if (!date) return '-'
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${month}/${day}`
}

function formatStampTime(dt) {
  const date = toDate(dt)
  if (!date) return ''
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${hours}:${minutes}`
}

function channelLabel(ch) {
  const map = { email: '邮件', web: '官网', event: '直播/活动', wechat: '微信' }
  return map[ch] || ch || '其他'
}

function sourceLabel(source) {
  const map = { linkflow: 'linkflow行为事件', zhique: '致趣行为事件', tianrun: '天润会话记录' }
  return map[source] || source || '未知来源'
}

function actorName(item) {
  return item?.contact_name || '未识别联系人'
}

function contentText(item) {
  return item?.content || item?.behavior_type || '无互动内容'
}

function behaviorType(item) {
  return item?.behavior_type || '互动事件'
}

function summaryText(item) {
  const type = behaviorType(item)
  return type === '互动事件' ? '客户发生互动事件' : `客户发生 ${type} 事件`
}
</script>

<template>
  <section class="timeline-panel">
    <header class="timeline-header">
      <div class="timeline-meta">
        <strong>近期互动</strong>
        <span class="timeline-tag">TIMELINE</span>
      </div>
      <div class="timeline-sub">
        <span>最近 18 条互动按时间线展示</span>
        <FieldHelpTooltip :help="help" align="end" />
      </div>
    </header>

    <div class="timeline-body">
      <div v-if="displayedInteractions.length" class="timeline-list">
        <article
          v-for="(item, idx) in displayedInteractions"
          :key="item.id || item.source_id || `${item.event_time}-${idx}`"
          class="timeline-item"
        >
          <div class="timeline-stamp">
            <b>{{ formatStampDate(item.event_time) }}</b>
            <span>{{ formatStampTime(item.event_time) }}</span>
          </div>

          <div class="timeline-card">
            <div class="timeline-title">
              <span class="timeline-badge timeline-badge--warn">{{ behaviorType(item) }}</span>
              <span class="timeline-badge">{{ channelLabel(item.channel) }}</span>
              <span class="timeline-badge timeline-badge--ok">{{ actorName(item) }}</span>
            </div>

            <div class="timeline-info-grid">
              <div class="timeline-info">
                <span>时间</span>
                <strong>{{ formatFullTime(item.event_time) }}</strong>
              </div>
              <div class="timeline-info">
                <span>来源</span>
                <strong>{{ sourceLabel(item.source_table) }}</strong>
              </div>
              <div class="timeline-info">
                <span>谁互动</span>
                <strong>{{ actorName(item) }}</strong>
              </div>
              <div class="timeline-info">
                <span>互动内容</span>
                <strong>{{ contentText(item) }}</strong>
              </div>
            </div>

            <p class="timeline-text">{{ summaryText(item) }}</p>
          </div>
        </article>
      </div>

      <div v-else class="timeline-empty">
        暂无互动记录
      </div>
    </div>
  </section>
</template>

<style scoped>
.timeline-panel {
  overflow: visible;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}

.timeline-header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--panel2), var(--panel));
}

.timeline-header::before {
  position: absolute;
  top: 0;
  left: 14px;
  width: 38px;
  height: 2px;
  background: linear-gradient(90deg, var(--brand), transparent);
  content: "";
}

.timeline-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.timeline-meta strong {
  color: var(--text);
  font-size: 14px;
  font-weight: 800;
}

.timeline-tag {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(101, 179, 255, .22);
  border-radius: 999px;
  padding: 4px 8px;
  background: rgba(101, 179, 255, .08);
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.timeline-sub {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.timeline-body {
  padding: 16px;
}

.timeline-list {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 14px;
}

.timeline-list::before {
  position: absolute;
  top: 4px;
  bottom: 4px;
  left: 6px;
  width: 1px;
  background: linear-gradient(180deg, rgba(101, 179, 255, .55), rgba(52, 211, 153, .2));
  content: "";
}

.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  align-items: flex-start;
}

.timeline-item::before {
  position: absolute;
  top: 16px;
  left: -12px;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--brand), var(--ok));
  box-shadow: 0 0 0 4px rgba(101, 179, 255, .12);
  content: "";
}

.timeline-stamp {
  padding-top: 4px;
  text-align: right;
}

.timeline-stamp b {
  display: block;
  color: var(--text);
  font-size: 12px;
  font-weight: 800;
}

.timeline-stamp span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}

.timeline-card {
  border: 1px solid rgba(101, 179, 255, .18);
  border-radius: 12px;
  padding: 12px;
  background:
    linear-gradient(180deg, rgba(101, 179, 255, .08), rgba(255, 255, 255, .03)),
    var(--panel2);
  box-shadow: 0 14px 30px rgba(0, 0, 0, .12);
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}

.timeline-card:hover {
  border-color: rgba(101, 179, 255, .38);
  box-shadow: 0 18px 36px rgba(0, 0, 0, .16);
  transform: translateY(-1px);
}

.timeline-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.timeline-badge {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  border: 1px solid rgba(101, 179, 255, .2);
  border-radius: 999px;
  padding: 3px 8px;
  background: rgba(101, 179, 255, .09);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
}

.timeline-badge--warn {
  border-color: rgba(251, 191, 36, .34);
  background: rgba(251, 191, 36, .12);
  color: var(--warn);
}

.timeline-badge--ok {
  border-color: rgba(52, 211, 153, .3);
  background: rgba(52, 211, 153, .12);
  color: var(--ok);
}

.timeline-info-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr);
  gap: 8px;
  margin-top: 10px;
}

.timeline-info {
  min-width: 0;
  border: 1px solid rgba(101, 179, 255, .14);
  border-radius: 8px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, .035);
}

.timeline-info span {
  display: block;
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 10.5px;
}

.timeline-info strong {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.45;
  text-overflow: ellipsis;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.timeline-text {
  margin: 8px 0 0;
  color: var(--text);
  font-size: 12px;
  line-height: 1.65;
}

.timeline-empty {
  padding: 28px 12px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

:global(html[data-theme="light"]) .timeline-panel {
  background: rgba(255, 255, 255, .82);
}

:global(html[data-theme="light"]) .timeline-header {
  background: linear-gradient(180deg, rgba(248, 251, 255, .96), rgba(238, 246, 255, .88));
}

:global(html[data-theme="light"]) .timeline-card {
  border-color: rgba(47, 127, 232, .16);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, .96), rgba(239, 247, 255, .86)),
    rgba(255, 255, 255, .92);
  box-shadow: 0 14px 34px rgba(40, 85, 140, .08);
}

:global(html[data-theme="light"]) .timeline-card:hover {
  border-color: rgba(47, 127, 232, .32);
  box-shadow: 0 18px 40px rgba(40, 85, 140, .12);
}

:global(html[data-theme="light"]) .timeline-info {
  border-color: rgba(166, 181, 205, .32);
  background: rgba(255, 255, 255, .62);
}

@media (max-width: 760px) {
  .timeline-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .timeline-sub {
    white-space: normal;
  }

  .timeline-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .timeline-stamp {
    padding-left: 2px;
    text-align: left;
  }

  .timeline-info-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
