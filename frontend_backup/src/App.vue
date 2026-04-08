<template>
  <div class="page">
    <header class="hero">
      <div>
        <h1>智慧宿舍能耗管控与碳中和系统</h1>
        <p>宿舍级实时监测 · 违章识别 · 智能断电 · 碳减排量化</p>
      </div>
      <div class="hero-status">
        <div class="status-item">
          <span class="label">系统状态</span>
          <span class="value online">在线运行</span>
        </div>
        <div class="status-item">
          <span class="label">当前时间</span>
          <span class="value">{{ currentTime }}</span>
        </div>
      </div>
    </header>

    <section class="card-grid">
      <div class="card metric-card power-card">
        <div class="card-title">实时功率</div>
        <div class="metric-value pulse">{{ realtime.power_w.toFixed(1) }}</div>
        <div class="metric-unit">W</div>
      </div>

      <div class="card metric-card">
        <div class="card-title">线路电压</div>
        <div class="metric-value">{{ realtime.voltage_v.toFixed(1) }}</div>
        <div class="metric-unit">V</div>
      </div>

      <div class="card metric-card">
        <div class="card-title">线路电流</div>
        <div class="metric-value">{{ realtime.current_a.toFixed(2) }}</div>
        <div class="metric-unit">A</div>
      </div>

      <div class="card metric-card">
        <div class="card-title">模块温度</div>
        <div class="metric-value">{{ realtime.temperature_c.toFixed(1) }}</div>
        <div class="metric-unit">℃</div>
      </div>

      <div class="card metric-card">
        <div class="card-title">漏电电流</div>
        <div class="metric-value">{{ realtime.leakage_current_ma.toFixed(1) }}</div>
        <div class="metric-unit">mA</div>
      </div>

      <div class="card metric-card carbon-card">
        <div class="card-title">实时碳排放</div>
        <div class="metric-value">{{ realtime.co2_emission_g_s.toFixed(4) }}</div>
        <div class="metric-unit">g/s</div>
      </div>
    </section>

    <section class="middle-grid">
      <div class="card big-panel">
        <div class="panel-header">
          <h2>动态监控看板</h2>
          <span class="tag">秒级刷新</span>
        </div>

        <div class="monitor-grid">
          <div class="mini-panel">
            <div class="mini-label">开关状态</div>
            <div class="switch-status" :class="realtime.breaker_on ? 'on' : 'off'">
              {{ realtime.breaker_on ? '已合闸' : '已分闸' }}
            </div>
          </div>

          <div class="mini-panel">
            <div class="mini-label">今日用电量</div>
            <div class="mini-value">{{ todayStats.energy_kwh.toFixed(3) }} kWh</div>
          </div>

          <div class="mini-panel">
            <div class="mini-label">今日累计碳排</div>
            <div class="mini-value">{{ todayStats.co2_g.toFixed(2) }} g</div>
          </div>

          <div class="mini-panel">
            <div class="mini-label">等效植树</div>
            <div class="mini-value">{{ todayStats.tree_equivalent.toFixed(3) }} 棵</div>
          </div>

          <div class="mini-panel">
            <div class="mini-label">当前模式</div>
            <div class="mini-value">{{ currentMode }}</div>
          </div>

          <div class="mini-panel">
            <div class="mini-label">告警状态</div>
            <div class="mini-value" :class="alarmList.length ? 'text-danger' : 'text-ok'">
              {{ alarmList.length ? '存在告警' : '运行正常' }}
            </div>
          </div>
        </div>
      </div>

      <div class="card big-panel carbon-wall">
        <div class="panel-header">
          <h2>碳中和墙</h2>
          <span class="tag green">节能减排竞赛展示</span>
        </div>

        <div class="carbon-content">
          <div class="carbon-big">{{ todayStats.saved_co2_g.toFixed(2) }} g</div>
          <div class="carbon-desc">今日累计减排量</div>

          <div class="carbon-row">
            <div class="carbon-box">
              <div class="carbon-label">节电量</div>
              <div class="carbon-number">{{ todayStats.saved_energy_kwh.toFixed(3) }} kWh</div>
            </div>
            <div class="carbon-box">
              <div class="carbon-label">等效植树</div>
              <div class="carbon-number">{{ todayStats.tree_equivalent.toFixed(3) }}</div>
            </div>
          </div>

          <div class="tree-line">
            🌱 🌳 🌱 🌳 🌱
          </div>
        </div>
      </div>
    </section>

    <section class="chart-grid">
      <div class="card chart-panel">
        <div class="panel-header">
          <h2>功率趋势图</h2>
          <button @click="refreshMockData">刷新模拟数据</button>
        </div>
        <div ref="powerChartRef" class="chart-box"></div>
      </div>

      <div class="card chart-panel">
        <div class="panel-header">
          <h2>环境与电流趋势</h2>
          <button @click="refreshMockData">刷新趋势</button>
        </div>
        <div ref="envChartRef" class="chart-box"></div>
      </div>
    </section>

    <section class="bottom-grid">
      <div class="card control-panel">
        <div class="panel-header">
          <h2>远程控制中心</h2>
          <span class="tag blue">模拟控制</span>
        </div>

        <div class="control-buttons">
          <button class="success-btn" @click="handleCloseBreaker">合闸</button>
          <button class="danger-btn" @click="handleOpenBreaker">分闸</button>
          <button class="warn-btn" @click="handleResetAlarm">报警复位</button>
        </div>

        <div class="control-buttons strategy-row">
          <button @click="setMode('正常模式')">正常模式</button>
          <button @click="setMode('离校模式')">一键离校模式</button>
          <button @click="setMode('睡眠节能模式')">睡眠节能模式</button>
        </div>

        <div class="control-log">
          <h3>控制反馈</h3>
          <p>{{ controlMessage }}</p>
        </div>
      </div>

      <div class="card alarm-panel">
        <div class="panel-header">
          <h2>告警中心</h2>
          <span class="tag red">AI识别/规则告警</span>
        </div>

        <div v-if="alarmList.length" class="alarm-list">
          <div v-for="item in alarmList" :key="item.id" class="alarm-item">
            <div class="alarm-top">
              <strong>{{ item.type }}</strong>
              <span class="alarm-time">{{ item.time }}</span>
            </div>
            <div class="alarm-desc">{{ item.message }}</div>
          </div>
        </div>

        <div v-else class="empty">
          当前无告警
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'

const powerChartRef = ref(null)
const envChartRef = ref(null)

let powerChart = null
let envChart = null
let timer = null
let clockTimer = null

const currentTime = ref('')
const currentMode = ref('正常模式')
const controlMessage = ref('系统已初始化，当前为模拟数据模式')

const realtime = reactive({
  power_w: 426.5,
  voltage_v: 220.8,
  current_a: 1.93,
  temperature_c: 31.6,
  leakage_current_ma: 2.3,
  breaker_on: true,
  co2_emission_g_s: 0.0676
})

const todayStats = reactive({
  energy_kwh: 3.426,
  co2_g: 1953.6,
  saved_co2_g: 326.8,
  saved_energy_kwh: 0.573,
  tree_equivalent: 0.018
})

const alarmList = ref([
  {
    id: 1,
    type: '疑似违章电器',
    message: '检测到功率突增且5秒内波动较小，疑似纯电阻负载接入',
    time: '2026-04-07 21:10:25'
  },
  {
    id: 2,
    type: '课表联动提醒',
    message: '当前为上课时段，宿舍功率高于待机阈值，存在空转风险',
    time: '2026-04-07 21:13:02'
  }
])

const history = ref(generateMockHistory())

function updateCurrentTime() {
  currentTime.value = new Date().toLocaleString('zh-CN', {
    hour12: false
  }).replace(/\//g, '-')
}

function calcCo2(powerW) {
  return (powerW / 3600 / 1000) * 570.3
}

function generateMockHistory() {
  const arr = []
  const now = Date.now()

  for (let i = 29; i >= 0; i--) {
    const time = new Date(now - i * 1000)
    const power = 280 + Math.random() * 280 + (Math.random() > 0.85 ? 500 : 0)
    const current = power / 220 + Math.random() * 0.2
    const temp = 29 + Math.random() * 5
    const voltage = 219 + Math.random() * 4

    arr.push({
      time: time.toLocaleTimeString('zh-CN', { hour12: false }),
      power: Number(power.toFixed(1)),
      current: Number(current.toFixed(2)),
      temp: Number(temp.toFixed(1)),
      voltage: Number(voltage.toFixed(1))
    })
  }

  return arr
}

function refreshRealtimeMock() {
  const powerBase = realtime.breaker_on ? 260 + Math.random() * 350 : 0
  const spike = Math.random() > 0.92 ? 900 : 0
  const newPower = powerBase + spike

  realtime.power_w = Number(newPower.toFixed(1))
  realtime.voltage_v = Number((219 + Math.random() * 4).toFixed(1))
  realtime.current_a = Number((newPower / 220).toFixed(2))
  realtime.temperature_c = Number((30 + Math.random() * 4).toFixed(1))
  realtime.leakage_current_ma = Number((1 + Math.random() * 3).toFixed(1))
  realtime.co2_emission_g_s = Number(calcCo2(realtime.power_w).toFixed(4))

  todayStats.energy_kwh = Number((todayStats.energy_kwh + realtime.power_w / 1000 / 3600).toFixed(3))
  todayStats.co2_g = Number((todayStats.co2_g + realtime.co2_emission_g_s).toFixed(2))
  todayStats.saved_co2_g = Number((300 + Math.random() * 60).toFixed(2))
  todayStats.saved_energy_kwh = Number((todayStats.saved_co2_g / 570.3).toFixed(3))
  todayStats.tree_equivalent = Number((todayStats.saved_co2_g / 18000).toFixed(3))

  history.value.push({
    time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    power: realtime.power_w,
    current: realtime.current_a,
    temp: realtime.temperature_c,
    voltage: realtime.voltage_v
  })

  if (history.value.length > 30) {
    history.value.shift()
  }

  if (realtime.power_w > 1000 && Math.random() > 0.5) {
    alarmList.value.unshift({
      id: Date.now(),
      type: '疑似违章电器',
      message: '系统检测到大功率稳定负载接入，建议立即核查',
      time: new Date().toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-')
    })

    if (alarmList.value.length > 6) {
      alarmList.value.pop()
    }
  }

  renderCharts()
}

function renderCharts() {
  if (!powerChartRef.value || !envChartRef.value) return

  if (!powerChart) {
    powerChart = echarts.init(powerChartRef.value)
  }

  if (!envChart) {
    envChart = echarts.init(envChartRef.value)
  }

  const xData = history.value.map(item => item.time)

  powerChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['功率', '电压'] },
    grid: { left: '5%', right: '5%', bottom: '10%', top: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData
    },
    yAxis: [
      {
        type: 'value',
        name: '功率(W)'
      },
      {
        type: 'value',
        name: '电压(V)'
      }
    ],
    series: [
      {
        name: '功率',
        type: 'line',
        smooth: true,
        areaStyle: {},
        data: history.value.map(item => item.power)
      },
      {
        name: '电压',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        data: history.value.map(item => item.voltage)
      }
    ]
  })

  envChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['电流', '温度'] },
    grid: { left: '5%', right: '5%', bottom: '10%', top: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData
    },
    yAxis: [
      {
        type: 'value',
        name: '电流(A)'
      },
      {
        type: 'value',
        name: '温度(℃)'
      }
    ],
    series: [
      {
        name: '电流',
        type: 'line',
        smooth: true,
        data: history.value.map(item => item.current)
      },
      {
        name: '温度',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        data: history.value.map(item => item.temp)
      }
    ]
  })
}

function handleCloseBreaker() {
  realtime.breaker_on = true
  controlMessage.value = '已发送合闸指令（模拟）'
}

function handleOpenBreaker() {
  realtime.breaker_on = false
  realtime.power_w = 0
  realtime.current_a = 0
  realtime.co2_emission_g_s = 0
  controlMessage.value = '已发送分闸指令（模拟）'
}

function handleResetAlarm() {
  alarmList.value = []
  controlMessage.value = '报警已复位（模拟）'
}

function setMode(mode) {
  currentMode.value = mode
  controlMessage.value = `已切换到 ${mode}（模拟）`

  if (mode === '离校模式') {
    realtime.breaker_on = false
    realtime.power_w = 0
    realtime.current_a = 0
    realtime.co2_emission_g_s = 0
  }

  if (mode === '睡眠节能模式') {
    realtime.power_w = Number((80 + Math.random() * 80).toFixed(1))
    realtime.current_a = Number((realtime.power_w / 220).toFixed(2))
    realtime.co2_emission_g_s = Number(calcCo2(realtime.power_w).toFixed(4))
  }

  if (mode === '正常模式') {
    realtime.breaker_on = true
  }
}

function refreshMockData() {
  history.value = generateMockHistory()
  renderCharts()
}

function handleResize() {
  powerChart && powerChart.resize()
  envChart && envChart.resize()
}

onMounted(async () => {
  updateCurrentTime()
  await nextTick()
  renderCharts()

  timer = setInterval(() => {
    refreshRealtimeMock()
  }, 1000)

  clockTimer = setInterval(() => {
    updateCurrentTime()
  }, 1000)

  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  timer && clearInterval(timer)
  clockTimer && clearInterval(clockTimer)
  window.removeEventListener('resize', handleResize)

  if (powerChart) {
    powerChart.dispose()
    powerChart = null
  }

  if (envChart) {
    envChart.dispose()
    envChart = null
  }
})
</script>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: "Microsoft YaHei", Arial, sans-serif;
  background: linear-gradient(180deg, #0f172a, #111827 40%, #0b1120);
  color: #e5eefc;
}

#app {
  min-height: 100vh;
}

.page {
  max-width: 1500px;
  margin: 0 auto;
  padding: 24px;
}

.hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 28px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.9), rgba(16, 185, 129, 0.85));
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
  margin-bottom: 24px;
}

.hero h1 {
  margin: 0 0 10px;
  font-size: 34px;
  color: #fff;
}

.hero p {
  margin: 0;
  color: rgba(255, 255, 255, 0.92);
}

.hero-status {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 260px;
}

.status-item {
  background: rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  padding: 12px 14px;
}

.label {
  display: block;
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  margin-bottom: 4px;
}

.value {
  font-size: 16px;
  font-weight: bold;
}

.online {
  color: #d1fae5;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 18px;
  margin-bottom: 24px;
}

.card {
  background: rgba(17, 24, 39, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
  backdrop-filter: blur(8px);
}

.metric-card {
  min-height: 160px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.power-card {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.35), rgba(14, 165, 233, 0.18)), rgba(17, 24, 39, 0.92);
}

.carbon-card {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.35), rgba(34, 197, 94, 0.15)), rgba(17, 24, 39, 0.92);
}

.card-title {
  color: #93c5fd;
  font-size: 15px;
  margin-bottom: 12px;
}

.metric-value {
  font-size: 34px;
  font-weight: 700;
  color: #fff;
}

.metric-unit {
  margin-top: 8px;
  color: #94a3b8;
  font-size: 14px;
}

.pulse {
  animation: pulseGlow 1.2s infinite;
}

@keyframes pulseGlow {
  0% { text-shadow: 0 0 0 rgba(96, 165, 250, 0.2); }
  50% { text-shadow: 0 0 18px rgba(96, 165, 250, 0.85); }
  100% { text-shadow: 0 0 0 rgba(96, 165, 250, 0.2); }
}

.middle-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

.big-panel {
  min-height: 280px;
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

.tag {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
  border: 1px solid rgba(96, 165, 250, 0.25);
}

.tag.green {
  color: #86efac;
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.2);
}

.tag.red {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.2);
}

.tag.blue {
  color: #bfdbfe;
}

.monitor-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.mini-panel {
  background: rgba(30, 41, 59, 0.7);
  border-radius: 14px;
  padding: 18px;
}

.mini-label {
  color: #94a3b8;
  font-size: 14px;
  margin-bottom: 10px;
}

.mini-value {
  font-size: 22px;
  font-weight: bold;
  color: #f8fafc;
}

.switch-status {
  display: inline-block;
  padding: 10px 16px;
  border-radius: 999px;
  font-weight: bold;
  font-size: 16px;
}

.switch-status.on {
  background: rgba(34, 197, 94, 0.15);
  color: #86efac;
}

.switch-status.off {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}

.text-danger {
  color: #fca5a5;
}

.text-ok {
  color: #86efac;
}

.carbon-wall {
  display: flex;
  flex-direction: column;
}

.carbon-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.carbon-big {
  font-size: 42px;
  font-weight: 800;
  color: #86efac;
}

.carbon-desc {
  color: #cbd5e1;
  margin-top: 8px;
  margin-bottom: 22px;
}

.carbon-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.carbon-box {
  background: rgba(30, 41, 59, 0.7);
  border-radius: 14px;
  padding: 16px;
}

.carbon-label {
  color: #94a3b8;
  margin-bottom: 8px;
}

.carbon-number {
  font-size: 24px;
  font-weight: bold;
  color: #f8fafc;
}

.tree-line {
  margin-top: 22px;
  font-size: 28px;
  letter-spacing: 6px;
}

.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

.chart-panel {
  min-height: 420px;
}

.chart-box {
  width: 100%;
  height: 340px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.control-buttons {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.strategy-row {
  margin-top: 8px;
}

.control-log {
  margin-top: 18px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(30, 41, 59, 0.7);
  color: #cbd5e1;
}

.alarm-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.alarm-item {
  padding: 16px;
  border-radius: 14px;
  background: rgba(127, 29, 29, 0.18);
  border: 1px solid rgba(248, 113, 113, 0.18);
}

.alarm-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: #fecaca;
  flex-wrap: wrap;
}

.alarm-desc {
  color: #f1f5f9;
}

.alarm-time {
  font-size: 13px;
  color: #fca5a5;
}

.empty {
  color: #94a3b8;
  padding: 30px 0;
  text-align: center;
}

button {
  border: none;
  border-radius: 10px;
  padding: 10px 16px;
  color: white;
  cursor: pointer;
  background: #2563eb;
  transition: 0.2s ease;
}

button:hover {
  transform: translateY(-1px);
  opacity: 0.95;
}

.success-btn {
  background: #16a34a;
}

.danger-btn {
  background: #dc2626;
}

.warn-btn {
  background: #d97706;
}

@media (max-width: 1300px) {
  .card-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .middle-grid,
  .chart-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .monitor-grid {
    grid-template-columns: 1fr 1fr;
  }

  .hero {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (max-width: 700px) {
  .card-grid,
  .monitor-grid,
  .carbon-row {
    grid-template-columns: 1fr;
  }

  .hero h1 {
    font-size: 26px;
  }

  .metric-value {
    font-size: 28px;
  }

  .carbon-big {
    font-size: 34px;
  }
}
</style>