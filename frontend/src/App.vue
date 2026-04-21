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

    <section class="channel-sections">
      <div v-for="channel in displayChannels" :key="channel" class="channel-card">
        <div class="channel-title-row">
          <h3>第{{ channel }}路</h3>
          <span class="channel-tag" :class="{ active: selectedChannel === channel }">实时数据</span>
        </div>
        <div class="metric-grid">
          <MetricCard title="线路功率" :value="channelRealtime(channel).power.toFixed(1)" unit="raw" :pulse="selectedChannel === channel" variant="power-card" />
          <MetricCard title="线路电压" :value="channelRealtime(channel).voltage.toFixed(1)" unit="V" />
          <MetricCard title="线路电流" :value="channelRealtime(channel).current.toFixed(2)" unit="A" />
          <MetricCard title="模块温度" :value="channelRealtime(channel).temperature.toFixed(1)" unit="℃" />
          <MetricCard title="漏电电流" :value="channelRealtime(channel).leakageCurrent.toFixed(1)" unit="raw" />
        </div>
      </div>
    </section>

    <section class="middle-grid">
      <MonitorSummary
        :realtime="selectedRealtimeForSummary"
        :stats="todayStats"
        :mode="currentMode"
        :alarm-count="alarmList.length"
      />
      <CarbonWall :stats="todayStats" />
    </section>

    <section class="chart-toolbar">
      <span>历史查看路数</span>
      <div class="channel-switch">
        <button
          v-for="channel in displayChannels"
          :key="`history-${channel}`"
          class="channel-switch-btn"
          :class="{ active: selectedChannel === channel }"
          @click="handleSelectChannel(channel)"
        >
          第{{ channel }}路
        </button>
      </div>
    </section>

    <section class="chart-grid">
      <PowerTrendChart :history="selectedHistory" :channel-label="`第${selectedChannel}路`" @refresh="refreshHistoryData" />
      <EnvTrendChart :history="selectedHistory" :channel-label="`第${selectedChannel}路`" @refresh="refreshHistoryData" />
    </section>

    <section class="bottom-grid">
      <ControlPanel
        :message="controlMessage"
        :selected-channel="selectedChannel"
        :channels="displayChannels"
        @select-channel="handleSelectChannel"
        @close-breaker="handleCloseBreaker"
        @open-breaker="handleOpenBreaker"
        @reset-alarm="handleResetAlarm"
        @set-mode="setMode"
      />
      <AlarmList :alarms="alarmList" />
    </section>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import MetricCard from './components/MetricCard.vue'
import CarbonWall from './components/CarbonWall.vue'
import AlarmList from './components/AlarmList.vue'
import ControlPanel from './components/ControlPanel.vue'
import MonitorSummary from './components/MonitorSummary.vue'
import PowerTrendChart from './components/PowerTrendChart.vue'
import EnvTrendChart from './components/EnvTrendChart.vue'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const displayChannels = [1, 2, 4]
const pollIntervalMs = 2000

let timer = null
let clockTimer = null

const currentTime = ref('')
const currentMode = ref('正常模式')
const controlMessage = ref('系统已初始化，当前为Modbus实时数据模式')
const selectedChannel = ref(1)

const alarmList = ref([
  {
    id: 1,
    type: '疑似违章电器',
    message: '检测到功率突增且5秒内波动较小，疑似纯电阻负载接入',
    time: '2026-04-07 21:10:25'
  }
])

function createEmptyChannelState() {
  return {
    power: 0,
    voltage: 0,
    current: 0,
    leakageCurrent: 0,
    temperature: 0,
    breakerOn: false
  }
}

const realtimeByChannel = reactive({
  1: createEmptyChannelState(),
  2: createEmptyChannelState(),
  4: createEmptyChannelState()
})

const historyByChannel = reactive({
  1: [],
  2: [],
  4: []
})

const todayStats = reactive({
  energy_kwh: 0,
  co2_g: 0,
  saved_co2_g: 0,
  saved_energy_kwh: 0,
  tree_equivalent: 0
})

const selectedRealtimeForSummary = computed(() => {
  const state = realtimeByChannel[selectedChannel.value] || createEmptyChannelState()
  const totalPower = displayChannels.reduce((sum, channel) => sum + channelRealtime(channel).power, 0)
  return {
    power_w: totalPower,
    voltage_v: state.voltage,
    current_a: state.current,
    temperature_c: state.temperature,
    leakage_current_ma: state.leakageCurrent,
    breaker_on: state.breakerOn,
    co2_emission_g_s: Number(calcCo2(totalPower).toFixed(4))
  }
})

const selectedHistory = computed(() => historyByChannel[selectedChannel.value] || [])

function channelRealtime(channel) {
  return realtimeByChannel[channel] || createEmptyChannelState()
}

function updateCurrentTime() {
  currentTime.value = new Date().toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-')
}

function calcCo2(powerW) {
  return (powerW / 3600 / 1000) * 570.3
}

function toNumber(value, fallback = 0) {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getChannelPayload(channels, channelNo) {
  return (channels || []).find(item => Number(item.ch) === Number(channelNo))
}

function applyChannelRealtime(channelNo, payload) {
  if (!payload || !realtimeByChannel[channelNo]) return
  realtimeByChannel[channelNo].power = toNumber(payload.power_raw ?? payload.power, 0)
  realtimeByChannel[channelNo].voltage = toNumber(payload.voltage_raw ?? payload.voltage, 0)
  realtimeByChannel[channelNo].current = toNumber(payload.current, 0)
  realtimeByChannel[channelNo].leakageCurrent = toNumber(payload.leakage_current_raw ?? payload.leakage_current, 0)
  realtimeByChannel[channelNo].temperature = toNumber(payload.temperature, 0)
  realtimeByChannel[channelNo].breakerOn = Boolean(payload.breaker_on)
}

function appendRealtimeHistory(timeText, channels) {
  for (const channel of displayChannels) {
    const payload = getChannelPayload(channels, channel)
    if (!payload) continue
    const series = historyByChannel[channel]
    series.push({
      time: timeText,
      power: toNumber(payload.power_raw ?? payload.power, 0),
      voltage: toNumber(payload.voltage_raw ?? payload.voltage, 0),
      current: toNumber(payload.current_raw ?? payload.current, 0),
      leakage: toNumber(payload.leakage_current_raw ?? payload.leakage_current, 0),
      temp: toNumber(payload.temperature, 0)
    })
    if (series.length > 30) {
      series.shift()
    }
  }
}

function updateTodayStatsByRealtime() {
  const totalPower = displayChannels.reduce((sum, channel) => sum + channelRealtime(channel).power, 0)
  const co2PerSecond = calcCo2(totalPower)
  const durationSec = pollIntervalMs / 1000

  todayStats.energy_kwh = Number((todayStats.energy_kwh + totalPower / 1000 / 3600 * durationSec).toFixed(3))
  todayStats.co2_g = Number((todayStats.co2_g + co2PerSecond * durationSec).toFixed(2))
  todayStats.saved_co2_g = Number((todayStats.saved_co2_g + 0.08).toFixed(2))
  todayStats.saved_energy_kwh = Number((todayStats.saved_co2_g / 570.3).toFixed(3))
  todayStats.tree_equivalent = Number((todayStats.saved_co2_g / 18000).toFixed(3))
}

function applyChannelsSnapshot(channels, recordTime, sourceLabel) {
  for (const channel of displayChannels) {
    applyChannelRealtime(channel, getChannelPayload(channels, channel))
  }
  appendRealtimeHistory(
    recordTime ? String(recordTime).slice(11) : new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    channels
  )
  updateTodayStatsByRealtime()
  controlMessage.value = sourceLabel
}

async function fetchRealtimeModbus() {
  try {
    const realtimeResp = await fetch(`${API_BASE}/api/realtime/modbus`)
    const realtimeJson = await realtimeResp.json()
    if (realtimeJson.code === 200 && realtimeJson.data?.channels?.length) {
      applyChannelsSnapshot(
        realtimeJson.data.channels,
        realtimeJson.data.record_time,
        `已同步实时数据（采样时间 ${realtimeJson.data.record_time}）`
      )
      return
    }

    const fallbackResp = await fetch(`${API_BASE}/api/modbus/test/read-all`)
    const fallbackJson = await fallbackResp.json()
    if (fallbackJson.code === 200 && fallbackJson.data?.channels?.length) {
      applyChannelsSnapshot(
        fallbackJson.data.channels,
        null,
        '数据库未就绪，当前显示串口直读实时数据'
      )
      return
    }

    controlMessage.value = `实时数据暂不可用：${realtimeJson.message || fallbackJson.message || '无数据'}`
  } catch (err) {
    controlMessage.value = `后端连接失败：${err.message || String(err)}`
  }
}

async function fetchHistoryModbus() {
  try {
    const resp = await fetch(`${API_BASE}/api/history/modbus?limit=30`)
    const json = await resp.json()
    if (json.code !== 200 || !Array.isArray(json.data)) {
      return
    }

    const rebuilt = { 1: [], 2: [], 4: [] }
    for (const row of json.data.slice().reverse()) {
      const time = String(row.record_time || '').slice(11) || new Date().toLocaleTimeString('zh-CN', { hour12: false })
      const channels = row.channels || []
      for (const channel of displayChannels) {
        const payload = getChannelPayload(channels, channel)
        if (!payload) continue
        rebuilt[channel].push({
          time,
          power: toNumber(payload.power_raw ?? payload.power, 0),
          voltage: toNumber(payload.voltage_raw ?? payload.voltage, 0),
          current: toNumber(payload.current, 0),
          leakage: toNumber(payload.leakage_current_raw ?? payload.leakage_current, 0),
          temp: toNumber(payload.temperature, 0)
        })
      }
    }

    for (const channel of displayChannels) {
      historyByChannel[channel] = rebuilt[channel]
    }
  } catch (err) {
    controlMessage.value = `历史数据加载失败：${err.message || String(err)}`
  }
}

async function sendControl(action) {
  try {
    const channel = selectedChannel.value
    const resp = await fetch(`${API_BASE}/api/control/breaker`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, action })
    })
    const json = await resp.json()
    if (json.code !== 200) {
      controlMessage.value = `控制失败：${json.message || 'unknown'}`
      return
    }

    const statusRaw = json.data?.status_raw || '--'
    controlMessage.value = `控制成功：第${channel}路${action === 'close' ? '合闸' : '分闸'}，状态=${statusRaw}`
    await fetchRealtimeModbus()
  } catch (err) {
    controlMessage.value = `控制请求失败：${err.message || String(err)}`
  }
}

function handleSelectChannel(channel) {
  selectedChannel.value = Number(channel)
}

function handleCloseBreaker() {
  sendControl('close')
}

function handleOpenBreaker() {
  sendControl('open')
}

function handleResetAlarm() {
  alarmList.value = []
  controlMessage.value = '报警已复位'
}

function setMode(mode) {
  currentMode.value = mode
  if (mode === '离校模式') {
    handleOpenBreaker()
    return
  }
  if (mode === '正常模式') {
    handleCloseBreaker()
    return
  }
  controlMessage.value = `已切换到 ${mode}`
}

function refreshHistoryData() {
  fetchHistoryModbus()
}

onMounted(() => {
  updateCurrentTime()
  fetchHistoryModbus()
  fetchRealtimeModbus()

  timer = setInterval(() => {
    fetchRealtimeModbus()
  }, pollIntervalMs)

  clockTimer = setInterval(() => {
    updateCurrentTime()
  }, 1000)
})

onBeforeUnmount(() => {
  timer && clearInterval(timer)
  clockTimer && clearInterval(clockTimer)
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

.middle-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.channel-sections {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

.channel-card {
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 14px;
  background: rgba(17, 24, 39, 0.92);
}

.channel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.channel-title-row h3 {
  margin: 0;
}

.channel-tag {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #93c5fd;
  border: 1px solid rgba(96, 165, 250, 0.25);
}

.channel-tag.active {
  color: #86efac;
  border-color: rgba(34, 197, 94, 0.35);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.chart-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  color: #cbd5e1;
}

.channel-switch {
  display: flex;
  gap: 8px;
}

.channel-switch-btn {
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(30, 41, 59, 0.7);
  color: #e2e8f0;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
}

.channel-switch-btn.active {
  background: #2563eb;
  border-color: #60a5fa;
}

@media (max-width: 1300px) {
  .metric-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .middle-grid,
  .chart-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (max-width: 700px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .hero h1 {
    font-size: 26px;
  }
}
</style>