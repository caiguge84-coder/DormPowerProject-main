<template>
  <div class="card chart-panel">
    <div class="panel-header">
      <h2>功率趋势图（{{ channelLabel }}）</h2>
      <button @click="$emit('refresh')">刷新历史</button>
    </div>
    <div ref="chartRef" class="chart-box"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  history: {
    type: Array,
    required: true
  },
  channelLabel: {
    type: String,
    default: '第1路'
  }
})

defineEmits(['refresh'])

const chartRef = ref(null)
let chart = null

function renderChart() {
  if (!chartRef.value) return

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['功率', '电压'] },
    grid: { left: '5%', right: '5%', bottom: '10%', top: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: props.history.map(item => item.time)
    },
    yAxis: [
      { type: 'value', name: '功率(W)' },
      { type: 'value', name: '电压(V)' }
    ],
    series: [
      {
        name: '功率',
        type: 'line',
        smooth: true,
        areaStyle: {},
        data: props.history.map(item => item.power)
      },
      {
        name: '电压',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        data: props.history.map(item => item.voltage)
      }
    ]
  })
}

function handleResize() {
  chart && chart.resize()
}

watch(
  () => props.history,
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true }
)

onMounted(() => {
  renderChart()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<style scoped>
.card {
  background: rgba(17, 24, 39, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
  backdrop-filter: blur(8px);
}

.chart-panel {
  min-height: 420px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.panel-header h2 {
  margin: 0;
  font-size: 22px;
  color: #f8fafc;
}

.chart-box {
  width: 100%;
  height: 340px;
}

button {
  border: none;
  border-radius: 10px;
  padding: 10px 16px;
  color: white;
  cursor: pointer;
  background: #2563eb;
}
</style>