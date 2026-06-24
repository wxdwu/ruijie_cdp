<script setup>
defineProps({
  help: {
    type: Object,
    required: true,
  },
  align: {
    type: String,
    default: 'start',
  },
})
</script>

<template>
  <span class="field-help" :class="`field-help--${align}`">
    <button
      type="button"
      class="field-help__trigger"
      :aria-label="`查看${help.title}字段口径`"
    >
      ?
    </button>
    <span class="field-help__panel" role="tooltip">
      <span class="field-help__kicker">字段口径</span>
      <span class="field-help__title">
        <span
          class="field-help__type"
          :class="help.type === 'src' ? 'field-help__type--src' : 'field-help__type--calc'"
        >
          {{ help.type === 'src' ? '源字段' : '计算' }}
        </span>
        {{ help.title }}
      </span>
      <span class="field-help__grid">
        <span class="field-help__row">
          <span>含义</span>
          <b>{{ help.meaning }}</b>
        </span>
        <span class="field-help__row">
          <span>来源表</span>
          <b>{{ help.sourceTables }}</b>
        </span>
        <span class="field-help__row">
          <span>来源字段</span>
          <b>{{ help.sourceFields }}</b>
        </span>
        <span class="field-help__row">
          <span>计算逻辑</span>
          <b>{{ help.calculation }}</b>
        </span>
        <span class="field-help__row">
          <span>空值处理</span>
          <b>{{ help.emptyState }}</b>
        </span>
      </span>
    </span>
  </span>
</template>

<style scoped>
.field-help {
  position: relative;
  z-index: 30;
  display: inline-flex;
  margin-left: 6px;
  vertical-align: middle;
}

.field-help__trigger {
  display: inline-flex;
  width: 17px;
  height: 17px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(90, 167, 255, .48);
  border-radius: 999px;
  background: rgba(90, 167, 255, .12);
  color: var(--brand);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  transition: background-color .15s ease, border-color .15s ease, transform .15s ease;
}

.field-help__trigger:hover,
.field-help__trigger:focus-visible {
  border-color: rgba(90, 167, 255, .75);
  background: rgba(90, 167, 255, .22);
  outline: none;
  transform: scale(1.06);
}

.field-help__panel {
  position: absolute;
  top: 24px;
  left: 0;
  display: none;
  width: min(360px, calc(100vw - 48px));
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: linear-gradient(180deg, var(--panel2), var(--panel));
  box-shadow: var(--shadow);
  color: var(--text);
  font-size: 11.5px;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
}

.field-help--end .field-help__panel {
  right: 0;
  left: auto;
}

.field-help:hover .field-help__panel,
.field-help:focus-within .field-help__panel {
  display: block;
}

.field-help__kicker {
  display: block;
  margin-bottom: 6px;
  color: var(--brand);
  font-size: 10px;
  font-weight: 800;
}

.field-help__title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text);
  font-size: 12.5px;
  font-weight: 800;
}

.field-help__type {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 800;
}

.field-help__type--src {
  border: 1px solid rgba(45, 212, 191, .32);
  background: rgba(45, 212, 191, .14);
  color: #2dd4bf;
}

.field-help__type--calc {
  border: 1px solid rgba(250, 204, 21, .30);
  background: rgba(250, 204, 21, .14);
  color: var(--warn);
}

.field-help__grid {
  display: grid;
  gap: 7px;
  margin-top: 10px;
}

.field-help__row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 10px;
  border-top: 1px dashed var(--line);
  padding-top: 7px;
}

.field-help__row:first-child {
  border-top: 0;
  padding-top: 0;
}

.field-help__row > span {
  color: var(--muted);
  font-weight: 700;
}

.field-help__row > b {
  color: var(--text);
  font-weight: 650;
}

:global(html[data-theme="light"]) .field-help__panel {
  border-color: rgba(166, 181, 205, .46);
  background: linear-gradient(180deg, rgba(255, 255, 255, .98), rgba(244, 248, 253, .96));
  box-shadow: 0 18px 48px rgba(21, 45, 83, .16);
}

:global(html[data-theme="light"]) .field-help__type--src {
  color: #168f82;
}

:global(html[data-theme="light"]) .field-help__type--calc {
  color: #9b7108;
}

</style>
