<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

use([BarChart, RadarChart, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  type: { type: String, required: true },
  labels: { type: Array, default: () => [] },
  unit: { type: String, default: '' },
  height: { type: Number, default: 280 },
})

const axisColor = 'rgba(159,176,208,.18)'
const labelColor = '#9aa8c2'
const textColor = '#edf2fb'
const blue = '#65b3ff'
const gray = '#64748b'
const green = '#34d399'

const option = computed(() => {
  if (props.type === 'radar') {
    return {
      animation: false,
      tooltip: { show: false },
      legend: {
        bottom: 0,
        textStyle: { color: labelColor, fontSize: 10 },
        itemWidth: 16,
        itemHeight: 3,
        data: ['本客户', '同行均值'],
      },
      radar: {
        center: ['50%', '47%'],
        radius: '63%',
        splitNumber: 4,
        indicator: props.labels.map(name => ({ name: `${name} 0${props.unit}`, max: 100 })),
        name: { color: labelColor, fontSize: 10 },
        axisLine: { lineStyle: { color: axisColor } },
        splitLine: { lineStyle: { color: axisColor } },
        splitArea: { areaStyle: { color: ['transparent'] } },
      },
      series: [{
        type: 'radar',
        symbol: 'none',
        data: [
          { name: '本客户', value: props.labels.map(() => 0), lineStyle: { color: blue }, areaStyle: { color: 'rgba(101,179,255,.08)' } },
          { name: '同行均值', value: props.labels.map(() => 0), lineStyle: { color: gray }, areaStyle: { color: 'rgba(100,116,139,.05)' } },
        ],
      }],
    }
  }

  if (props.type === 'stack') {
    return {
      animation: false,
      tooltip: { show: false },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: labelColor, fontSize: 10 },
        itemWidth: 14,
        itemHeight: 3,
      },
      grid: { left: 95, right: 30, top: 38, bottom: 16 },
      xAxis: {
        type: 'value',
        min: 0,
        max: 1,
        splitLine: { lineStyle: { color: 'rgba(159,176,208,.08)' } },
        axisLabel: { color: labelColor, fontSize: 9, formatter: `0${props.unit}` },
      },
      yAxis: {
        type: 'category',
        data: ['本客户', '同行均值'],
        axisLine: { lineStyle: { color: axisColor } },
        axisTick: { show: false },
        axisLabel: { color: labelColor, fontSize: 10 },
      },
      series: props.labels.map((name, index) => ({
        name,
        type: 'bar',
        stack: 'total',
        barWidth: 18,
        data: [0, 0],
        itemStyle: { color: [blue, green, '#fbbf24', '#c084fc', '#fb7185', '#22d3ee'][index % 6] },
        label: { show: false },
      })),
    }
  }

  const rows = props.labels
  return {
    animation: false,
    tooltip: { show: false },
    grid: { left: 150, right: 52, top: 8, bottom: 20 },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      splitLine: { lineStyle: { color: 'rgba(159,176,208,.08)' } },
      axisLabel: { color: labelColor, fontSize: 9, formatter: `0${props.unit}` },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: labelColor, fontSize: 10 },
    },
    series: [{
      type: 'bar',
      barWidth: 9,
      data: rows.map((_, index) => ({
        value: 0,
        itemStyle: { color: index % 2 ? gray : blue },
      })),
      showBackground: true,
      backgroundStyle: { color: 'rgba(255,255,255,.045)' },
      label: {
        show: true,
        position: 'right',
        color: textColor,
        fontSize: 10,
        formatter: `0${props.unit}`,
      },
    }],
  }
})
</script>

<template>
  <VChart class="prototype-chart" :option="option" autoresize :style="{ height: `${height}px` }" />
</template>
