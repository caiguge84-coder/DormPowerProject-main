<template>
  <div class="app">
    <div class="bg-glow bg-glow-1"></div>
    <div class="bg-glow bg-glow-2"></div>
    <div class="container">
      <section class="defense-topbar">
        <div class="defense-left">
          <div class="defense-title">竞赛答辩展示模式</div>
          <div class="defense-meta">
            <span>项目：宿舍用电监测与碳中和演示平台</span>
            <span>队伍：智能节能战队</span>
            <span>指导方向：智慧能源管理</span>
          </div>
        </div>
        <div class="defense-right">
          <div class="clock">{{ nowTimeText }}</div>
          <button class="ghost-btn" @click="toggleFullscreen">
            {{ isFullscreen ? '退出全屏' : '进入全屏' }}
          </button>
        </div>
      </section>

      <header class="header">
        <p class="header-kicker">Smart Dorm Energy Control Center</p>
        <h1>宿舍用电监测与碳中和演示平台</h1>
        <p class="subtitle">基于 RS485 / Modbus RTU 的智能空开竞赛级实时监测系统</p>
        <div class="headline-tags">
          <span class="tag-chip">秒级采样</span>
          <span class="tag-chip">WebSocket 推送</span>
          <span class="tag-chip">规则策略联动</span>
          <span class="tag-chip">手册严格模式</span>
        </div>
      </header>

      <section class="toolbar">
        <div class="backend-config">
          <label>后端地址：</label>
          <input v-model="baseUrl" class="url-input" />
        </div>

        <div class="btn-group">
          <button @click="fetchRealtime" :disabled="loading">
            {{ loading ? '刷新中...' : '立即刷新' }}
          </button>
          <button @click="scanDevice" :disabled="loading">
            扫描设备
          </button>
        </div>
      </section>

      <section class="status-bar">
        <div class="status-item">
          <span class="label">后端状态：</span>
          <span :class="backendOnline ? 'ok' : 'error'">
            {{ backendOnline ? '在线' : '离线/读取失败' }}
          </span>
        </div>
        <div class="status-item">
          <span class="label">串口：</span>
          <span>{{ port || '-' }}</span>
        </div>
        <div class="status-item">
          <span class="label">波特率：</span>
          <span>{{ baudrate || '-' }}</span>
        </div>
        <div class="status-item">
          <span class="label">设备地址：</span>
          <span>{{ slaveId || '-' }}</span>
        </div>
        <div class="status-item">
          <span class="label">最后更新时间：</span>
          <span>{{ lastUpdateText }}</span>
        </div>
        <div class="status-item">
          <span class="label">WebSocket：</span>
          <span :class="wsConnected ? 'ok' : 'error'">
            {{ wsConnected ? '已连接' : '未连接（轮询中）' }}
          </span>
        </div>
      </section>

      <section v-if="message" class="message" :class="backendOnline ? 'success' : 'error-box'">
        {{ message }}
      </section>

      <section class="grid">
        <div class="card">
          <h3>线路电压</h3>
          <div class="value">{{ formatNumber(realtime.voltage_v) }}</div>
          <div class="unit">V</div>
        </div>

        <div class="card">
          <h3>线路功率</h3>
          <div class="value">{{ formatNumber(realtime.power_w) }}</div>
          <div class="unit">W（手册未确认）</div>
        </div>

        <div class="card">
          <h3>线路电流</h3>
          <div class="value">{{ formatNumber(realtime.current_a) }}</div>
          <div v-if="realtime.current_a_quality !== 'good'" class="quality-badge">
            {{ realtime.current_a_quality === 'stale' ? '缓存值' : '降级值' }}
          </div>
          <div class="unit">A</div>
        </div>

        <div class="card">
          <h3>模块温度</h3>
          <div class="value">{{ formatNumber(realtime.temperature_c) }}</div>
          <div class="unit">℃（手册未确认）</div>
        </div>

        <div class="card">
          <h3>漏电电流</h3>
          <div class="value">{{ formatNumber(realtime.leakage_current_ma) }}</div>
          <div class="unit">mA</div>
        </div>

        <div class="card">
          <h3>累计电量</h3>
          <div class="value">{{ formatNumber(realtime.energy_kwh) }}</div>
          <div class="unit">kWh（手册未确认）</div>
        </div>

        <div class="card">
          <h3>实时碳排</h3>
          <div class="value">{{ formatNumber(realtime.co2_emission_g_s) }}</div>
          <div class="unit">g/s</div>
        </div>

        <div class="card">
          <h3>环境湿度</h3>
          <div class="value">{{ formatNumber(realtime.humidity_rh) }}</div>
          <div class="unit">%RH</div>
        </div>

        <div class="card">
          <h3>体感温度</h3>
          <div class="value">{{ formatNumber(realtime.feels_like_c) }}</div>
          <div class="unit">℃</div>
        </div>

        <div class="card">
          <h3>环境状态</h3>
          <div class="value">{{ realtime.environment_status || '-' }}</div>
          <div class="unit">舒适度</div>
        </div>

        <div class="card">
          <h3>断路器状态</h3>
          <div class="value" :class="realtime.breaker_on ? 'on' : 'off'">
            {{ realtime.breaker_on ? '合闸/运行中' : '分闸/无负载' }}
          </div>
          <div class="unit">状态</div>
        </div>
      </section>

      <section class="panel">
        <h2>碳中和墙（今日/累计）</h2>
        <div class="metrics-grid">
          <div class="metric-item">
            <span class="raw-label">采样点数：</span>
            <span>{{ metrics.sample_count }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">今日碳排：</span>
            <span>{{ formatNumber(carbonWall.today_co2_kg) }} kg</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">累计碳排：</span>
            <span>{{ formatNumber(carbonWall.total_co2_kg) }} kg</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">减排估算：</span>
            <span>{{ formatNumber(carbonWall.estimated_reduction_kg) }} kg</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">等效植树：</span>
            <span>{{ formatNumber(carbonWall.equivalent_trees) }} 棵</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">碳排因子：</span>
            <span>{{ formatNumber(carbonWall.carbon_factor_kg_per_kwh) }} kg/kWh</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">策略动作：</span>
            <span>{{ metrics.strategy_action_count }}</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>告警与识别区</h2>
        <div class="raw-row">
          <span class="raw-label">最新识别：</span>
          <span>{{ nilmSummary }}</span>
        </div>
        <div v-if="alarms.length === 0" class="empty">
          当前无告警
        </div>
        <div v-else class="alarm-list">
          <div v-for="alarm in alarms" :key="alarm.id" class="alarm-item">
            <div class="alarm-title">{{ alarm.type }}</div>
            <div class="alarm-msg">{{ alarm.message }}</div>
            <div class="alarm-time">{{ alarm.time }}</div>
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>原始数据</h2>
        <div class="raw-row">
          <span class="raw-label">响应格式：</span>
          <span>{{ realtime.frame_type || '-' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">原始寄存器：</span>
          <span>{{ formatRegisters(realtime.raw_registers) }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">原始响应帧：</span>
          <span class="raw-response">{{ realtime.raw_response || '-' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">告警状态值：</span>
          <span>{{ realtime.alarm_status ?? '-' }}</span>
        </div>
      </section>

      <section class="panel">
        <h2>后端可读数据整合</h2>
        <div class="raw-row">
          <span class="raw-label">输入寄存器 0x0000~0x0005：</span>
          <span>{{ formatRegisters(readableSummary.input_registers_0x0000_0x0005) }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">Guide03 总电压块：</span>
          <span>{{ formatRegisters(readableSummary.guide03_total_voltage) }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">Guide03 电流块：</span>
          <span>{{ formatRegisters(readableSummary.guide03_current) }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">线圈激活位：</span>
          <span>{{ readableSummary.coils_active.length ? readableSummary.coils_active.join(', ') : '-' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">离散激活位：</span>
          <span>{{ readableSummary.discrete_active.length ? readableSummary.discrete_active.join(', ') : '-' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">读取错误：</span>
          <span>{{ readableSummary.errors_text || '无' }}</span>
        </div>
      </section>

      <section class="panel">
        <h2>手册分路状态与告警位</h2>
        <div class="raw-row">
          <span class="raw-label">严格手册模式：</span>
          <span :class="realtime.strict_manual_mode ? 'ok' : 'error'">{{ realtime.strict_manual_mode ? '是' : '否' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">未确认字段：</span>
          <span>{{ realtime.manual_unconfirmed_fields.length ? realtime.manual_unconfirmed_fields.join(', ') : '-' }}</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">分路状态：</span>
          <span v-if="realtime.switch_states.length">
            <span v-for="item in realtime.switch_states" :key="item.switch_no" class="tag">
              {{ item.switch_no }}路: {{ item.state === 'close_on' ? '合闸' : item.state === 'open_off' ? '分闸' : '未知' }}
            </span>
          </span>
          <span v-else>-</span>
        </div>
        <div class="raw-row">
          <span class="raw-label">告警位（高字节）：</span>
          <span v-if="realtime.alarm_details.length">
            <span v-for="item in realtime.alarm_details" :key="`alarm-${item.switch_no}`" class="tag">
              {{ item.switch_no }}路: {{ item.active_bits_hi.length ? item.active_bits_hi.join('/') : '无' }}
            </span>
          </span>
          <span v-else>-</span>
        </div>
      </section>

      <section class="panel">
        <h2>控制中心与策略模式</h2>
        <div class="metrics-grid">
          <div class="metric-item">
            <span class="raw-label">控制模式：</span>
            <span>{{ controlPanel.mode }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">默认线圈：</span>
            <span>{{ controlPanel.default_coil_addr_hex }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">目标线圈：</span>
            <select v-model.number="controlPanel.selected_coil_addr" class="control-select">
              <option v-for="item in controlPanel.coil_options" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </div>
          <div class="metric-item">
            <span class="raw-label">课表联动：</span>
            <span>{{ controlPanel.schedule_linked ? '启用' : '关闭' }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">策略模式：</span>
            <span>{{ strategy.mode }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">功率阶跃：</span>
            <span>{{ formatNumber(strategy.power_step_w) }} W</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">课表时段：</span>
            <span>{{ strategy.in_class_time ? '是' : '否' }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">空转时长：</span>
            <span>{{ strategy.idle_duration_s }} s</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">自动断电触发：</span>
            <span>{{ strategy.auto_cutoff_triggered ? '已触发' : '未触发' }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">摘要轮询：</span>
            <span :class="readableSummaryPaused ? 'error' : 'ok'">{{ readableSummaryPaused ? '已暂停' : '运行中' }}</span>
          </div>
          <div class="metric-item">
            <span class="raw-label">控制维护模式：</span>
            <span :class="maintenanceMode ? 'error' : 'ok'">{{ maintenanceMode ? '已开启' : '未开启' }}</span>
          </div>
        </div>
        <div class="btn-group" style="margin-top:12px;">
          <button @click="setControlMode('manual')">手动模式</button>
          <button @click="setControlMode('auto')">自动模式</button>
          <button @click="setControlMode('protect')">保护模式</button>
          <button @click="toggleMaintenanceMode">{{ maintenanceMode ? '退出维护模式' : '进入维护模式' }}</button>
          <button @click="toggleReadableSummaryPolling">{{ readableSummaryPaused ? '恢复摘要轮询' : '暂停摘要轮询' }}</button>
          <button @click="probeCoils" :disabled="probeRunning">线圈巡检</button>
          <button @click="doControl('open')">分闸</button>
          <button @click="doControl('close')">合闸</button>
        </div>
        <div class="raw-row" v-if="controlPanel.last_ack">
          <span class="raw-label">最近回执：</span>
          <span>{{ controlPanel.last_ack.ack_id }} / {{ controlPanel.last_ack.action }} / {{ controlPanel.last_ack.coil_addr_hex || '-' }} / {{ controlPanel.last_ack.success ? '成功' : '失败' }}</span>
        </div>
        <div class="raw-row" v-if="probeResults.length">
          <span class="raw-label">巡检结果：</span>
          <span v-for="item in probeResults" :key="item.coil_addr_hex" class="tag">
            {{ item.coil_addr_hex }}: {{ item.ok ? 'ACK成功' : '失败' }} / {{ item.stateSummary }}
          </span>
        </div>
      </section>

      <section class="panel chart-panel">
        <h2>实时曲线（功率/电流/电压）</h2>
        <v-chart class="chart" :option="chartOption" autoresize />
      </section>

      <section class="panel">
        <div class="defense-guide-header">
          <h2>答辩讲解引导</h2>
          <button class="ghost-btn" @click="toggleGuideAutoPlay">
            {{ guideAutoPlay ? '暂停轮播' : '继续轮播' }}
          </button>
        </div>
        <div class="defense-guide-card">
          <div class="guide-step">Step {{ currentGuideIndex + 1 }}/{{ defenseGuides.length }}</div>
          <div class="guide-title">{{ currentGuide.title }}</div>
          <div class="guide-text">{{ currentGuide.text }}</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const baseUrl = ref('http://127.0.0.1:8001')

const loading = ref(false)
const backendOnline = ref(false)
const message = ref('')

const port = ref('')
const baudrate = ref('')
const slaveId = ref('')
const lastUpdate = ref(null)

const alarms = ref([])
const wsConnected = ref(false)
const metrics = reactive({
  sample_count: 0,
  avg_power_w: 0,
  co2_kg_total: 0,
  alarm_count: 0,
  strategy_action_count: 0,
  estimated_energy_saving_rate_percent: 0
})
const carbonWall = reactive({
  today_co2_kg: 0,
  total_co2_kg: 0,
  estimated_reduction_kg: 0,
  equivalent_trees: 0,
  carbon_factor_kg_per_kwh: 0.5703
})
const controlPanel = reactive({
  mode: 'manual',
  schedule_linked: true,
  last_ack: null,
  default_coil_addr_hex: '0x0003',
  selected_coil_addr: 3,
  coil_options: [
    { value: 0, label: '0x0000 / 1路' },
    { value: 1, label: '0x0001 / 2路' },
    { value: 3, label: '0x0003 / 默认' }
  ]
})
const nilmEvents = ref([])
const readableSummary = reactive({
  input_registers_0x0000_0x0005: [],
  guide03_total_voltage: [],
  guide03_current: [],
  coils_active: [],
  discrete_active: [],
  errors_text: ''
})
const strategy = reactive({
  mode: 'rule+ai',
  power_step_w: 0,
  in_class_time: false,
  idle_duration_s: 0,
  auto_cutoff_triggered: false
})
const trend = reactive({
  labels: [],
  power: [],
  current: [],
  voltage: []
})

const realtime = reactive({
  frame_type: '',
  raw_response: '',
  raw_registers: [],
  voltage_v: 0,
  leakage_current_ma: 0,
  power_w: 0,
  temperature_c: 0,
  current_a: 0,
  current_a_quality: 'unknown',
  alarm_status: 0,
  energy_kwh: 0,
  breaker_on: false,
  co2_emission_g_s: 0,
  humidity_rh: 0,
  feels_like_c: 0,
  environment_status: '',
  strict_manual_mode: false,
  manual_unconfirmed_fields: [],
  switch_states: [],
  alarm_details: [],
  timestamp: 0
})

let timer = null
let metricsTimer = null
let readableTimer = null
let carbonTimer = null
let controlTimer = null
let nilmTimer = null
let ws = null
let clockTimer = null
let guideTimer = null
const isFullscreen = ref(false)
const nowTimeText = ref('')
const guideAutoPlay = ref(true)
const currentGuideIndex = ref(0)
const readableSummaryPaused = ref(false)
const maintenanceMode = ref(false)
const probeRunning = ref(false)
const probeResults = ref([])
const defenseGuides = [
  { title: '硬件真实接入', text: '电脑通过 USB 转 RS485 接入智能空气开关，后端按 Modbus RTU 手册标准格式进行实时采集。' },
  { title: '秒级数据链路', text: '系统以秒级频率采样并通过 WebSocket 推送，前端大屏实时刷新关键指标与趋势曲线。' },
  { title: '手册严格模式', text: '字段仅使用手册确认地址，未确认项明确标注，保证数据可解释、可复核、可答辩。' },
  { title: '策略联动能力', text: '支持告警、策略动作记录与控制中心联动，具备后续扩展 AI 识别与自动治理基础。' }
]
const currentGuide = computed(() => defenseGuides[currentGuideIndex.value] || defenseGuides[0])
const nilmSummary = computed(() => {
  if (!nilmEvents.value.length) return '暂无违章识别事件'
  const e = nilmEvents.value[0]
  return `${e.label || 'unknown'} / 风险分 ${formatNumber(e.risk_score)} / 阶跃 ${formatNumber(e.step_w)}W`
})

const lastUpdateText = computed(() => {
  if (!lastUpdate.value) return '-'
  return new Date(lastUpdate.value).toLocaleString()
})

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-'
  }
  return Number(value).toFixed(2)
}

function formatRegisters(regs) {
  if (!regs || !regs.length) return '-'
  return `[${regs.join(', ')}]`
}

function applyRealtimeRaw(d = {}, extra = {}) {
  realtime.frame_type = d.frame_type || ''
  realtime.raw_response = d.raw_response || ''
  realtime.raw_registers = Array.isArray(d.raw_registers) ? d.raw_registers : []
  realtime.voltage_v = d.voltage_v ?? 0
  realtime.leakage_current_ma = d.leakage_current_ma ?? 0
  realtime.power_w = d.power_w ?? 0
  realtime.temperature_c = d.temperature_c ?? 0
  const nextCurrent = Number(d.current_a)
  if (d.current_a === null || d.current_a === undefined || Number.isNaN(nextCurrent)) {
    // 保留上次有效值，避免后端瞬时异常导致前端误判为回零。
    realtime.current_a_quality = 'stale'
  } else {
    realtime.current_a = nextCurrent
    realtime.current_a_quality = d.quality_flag === 'degraded' ? 'degraded' : 'good'
  }
  realtime.alarm_status = d.alarm_status ?? 0
  realtime.energy_kwh = d.energy_kwh ?? 0
  realtime.breaker_on = Boolean(d.breaker_on) || Number(d.power_w ?? 0) > 5 || Number(realtime.current_a ?? 0) > 0.02
  realtime.co2_emission_g_s = d.co2_emission_g_s ?? ((extra.co2_kg_per_hour ?? 0) * 1000 / 3600)
  realtime.humidity_rh = d.humidity_rh ?? 0
  realtime.feels_like_c = d.feels_like_c ?? d.temperature_c ?? 0
  realtime.environment_status = d.environment_status || ''
  realtime.strict_manual_mode = Boolean(d.strict_manual_mode)
  realtime.manual_unconfirmed_fields = Array.isArray(d.manual_unconfirmed_fields) ? d.manual_unconfirmed_fields : []
  realtime.switch_states = Array.isArray(d.switch_states) ? d.switch_states : []
  realtime.alarm_details = Array.isArray(d.alarm_details) ? d.alarm_details : []
  realtime.timestamp = d.timestamp ?? 0

  const nowLabel = new Date().toLocaleTimeString()
  trend.labels.push(nowLabel)
  trend.power.push(Number(realtime.power_w) || 0)
  trend.current.push(Number.isFinite(Number(realtime.current_a)) ? Number(realtime.current_a) : 0)
  trend.voltage.push(Number(realtime.voltage_v) || 0)
  if (trend.labels.length > 60) {
    trend.labels.shift()
    trend.power.shift()
    trend.current.shift()
    trend.voltage.shift()
  }
}

function applyRealtimeData(res) {
  port.value = res.port ?? ''
  baudrate.value = res.baudrate ?? ''
  slaveId.value = res.slave_id ?? ''
  alarms.value = Array.isArray(res.alarms) ? res.alarms : []

  applyRealtimeRaw(res.data || {})
  lastUpdate.value = Date.now()
}

async function fetchStatus() {
  try {
    const res = await fetch(`${baseUrl.value}/api/status`)
    const payload = await res.json()
    if (!payload.success) return
    const config = payload.data?.config || {}
    port.value = config.port ?? port.value ?? ''
    baudrate.value = config.baudrate ?? baudrate.value ?? ''
    slaveId.value = config.slave_id ?? slaveId.value ?? ''
    controlPanel.default_coil_addr_hex = config.breaker_coil_addr || controlPanel.default_coil_addr_hex
    const parsedDefaultCoil = Number.parseInt(String(config.breaker_coil_addr || '').replace(/^0x/i, ''), 16)
    if (Number.isInteger(parsedDefaultCoil) && parsedDefaultCoil >= 0) {
      controlPanel.selected_coil_addr = parsedDefaultCoil
      const exists = controlPanel.coil_options.some((item) => item.value === parsedDefaultCoil)
      if (!exists) {
        controlPanel.coil_options.push({
          value: parsedDefaultCoil,
          label: `${config.breaker_coil_addr} / 默认`
        })
      }
    }
  } catch (err) {
    // silent: status is auxiliary and should not break realtime flow
  }
}

async function fetchRealtime() {
  loading.value = true
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 3500)
  try {
    const res = await fetch(`${baseUrl.value}/api/realtime`, { signal: controller.signal })
    const guideData = await res.json()
    if (!guideData.success) {
      throw new Error(guideData.message || '读取失败')
    }
    backendOnline.value = true
    message.value = guideData.note ? `实时数据读取成功（${guideData.note}）` : '实时数据读取成功'
    applyRealtimeData(guideData)
  } catch (err) {
    if (err.name === 'AbortError') {
      message.value = '实时读取超时，已切换等待下一次缓存更新'
      return
    }
    backendOnline.value = false
    message.value = `请求失败：${err.message}`
  } finally {
    clearTimeout(timeoutId)
    loading.value = false
  }
}

async function fetchMetrics() {
  try {
    const res = await fetch(`${baseUrl.value}/api/metrics/summary?hours=24`)
    const data = await res.json()
    if (!data.success) return
    metrics.sample_count = data.sample_count ?? 0
    metrics.avg_power_w = data.avg_power_w ?? 0
    metrics.co2_kg_total = data.co2_kg_total ?? 0
    metrics.alarm_count = data.alarm_count ?? 0
    metrics.strategy_action_count = data.strategy_action_count ?? 0
    metrics.estimated_energy_saving_rate_percent = data.estimated_energy_saving_rate_percent ?? 0
  } catch (err) {
    // keep silent, avoid breaking realtime loop
  }
}

async function fetchCarbonWall() {
  try {
    const res = await fetch(`${baseUrl.value}/api/dashboard/carbon_wall`)
    const payload = await res.json()
    if (!payload.success) return
    const d = payload.data || {}
    carbonWall.today_co2_kg = d.today_co2_kg ?? 0
    carbonWall.total_co2_kg = d.total_co2_kg ?? 0
    carbonWall.estimated_reduction_kg = d.estimated_reduction_kg ?? 0
    carbonWall.equivalent_trees = d.equivalent_trees ?? 0
    carbonWall.carbon_factor_kg_per_kwh = d.carbon_factor_kg_per_kwh ?? 0.5703
  } catch (err) {
    // silent
  }
}

async function fetchControlPanel() {
  try {
    const res = await fetch(`${baseUrl.value}/api/dashboard/strategy_panel`)
    const payload = await res.json()
    if (!payload.success) return
    const d = payload.data || {}
    controlPanel.mode = d.mode || 'manual'
    controlPanel.last_ack = d.last_control_ack || null
  } catch (err) {
    // silent
  }
}

async function fetchNilmEvents() {
  try {
    const res = await fetch(`${baseUrl.value}/api/nilm/events?limit=20`)
    const payload = await res.json()
    if (!payload.success) return
    nilmEvents.value = payload.data?.items || []
  } catch (err) {
    // silent
  }
}

async function fetchReadableSummary() {
  if (readableSummaryPaused.value) return
  try {
    const res = await fetch(`${baseUrl.value}/api/readable/summary`)
    const data = await res.json()
    if (!data.success) return

    readableSummary.input_registers_0x0000_0x0005 = data.input_registers_0x0000_0x0005 || []
    readableSummary.guide03_total_voltage = data.guide03_blocks?.total_voltage?.registers || []
    readableSummary.guide03_current = data.guide03_blocks?.current?.registers || []
    readableSummary.coils_active = data.coils?.active_addrs_hex || []
    readableSummary.discrete_active = data.discrete_inputs?.active_addrs_hex || []

    const errs = data.errors || {}
    readableSummary.errors_text = Object.keys(errs).length
      ? Object.entries(errs).map(([k, v]) => `${k}: ${v}`).join(' | ')
      : ''
  } catch (err) {
    // silent fallback
  }
}

function startReadableSummaryPolling() {
  if (readableTimer) clearInterval(readableTimer)
  if (readableSummaryPaused.value) return
  readableTimer = setInterval(fetchReadableSummary, 10000)
}

function stopBackgroundPolling({ keepClock = true, keepGuide = true } = {}) {
  if (timer) clearInterval(timer)
  if (metricsTimer) clearInterval(metricsTimer)
  if (readableTimer) clearInterval(readableTimer)
  if (carbonTimer) clearInterval(carbonTimer)
  if (controlTimer) clearInterval(controlTimer)
  if (nilmTimer) clearInterval(nilmTimer)
  timer = null
  metricsTimer = null
  readableTimer = null
  carbonTimer = null
  controlTimer = null
  nilmTimer = null
  if (!keepClock && clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  if (!keepGuide && guideTimer) {
    clearInterval(guideTimer)
    guideTimer = null
  }
  if (ws) {
    ws.close()
    ws = null
  }
}

function startBackgroundPolling() {
  timer = setInterval(fetchRealtime, 5000)
  metricsTimer = setInterval(fetchMetrics, 10000)
  carbonTimer = setInterval(fetchCarbonWall, 12000)
  controlTimer = setInterval(fetchControlPanel, 8000)
  nilmTimer = setInterval(fetchNilmEvents, 10000)
  startReadableSummaryPolling()
  if (!ws) connectWebSocket()
}

function toggleReadableSummaryPolling() {
  readableSummaryPaused.value = !readableSummaryPaused.value
  if (readableSummaryPaused.value) {
    if (readableTimer) {
      clearInterval(readableTimer)
      readableTimer = null
    }
    message.value = '已手动暂停 /api/readable/summary 轮询，可先尝试分合闸'
    return
  }
  fetchReadableSummary()
  startReadableSummaryPolling()
  message.value = '已恢复 /api/readable/summary 轮询'
}

function toggleMaintenanceMode() {
  maintenanceMode.value = !maintenanceMode.value
  if (maintenanceMode.value) {
    readableSummaryPaused.value = true
    stopBackgroundPolling()
    wsConnected.value = false
    message.value = '已进入控制维护模式：已暂停实时/摘要/统计/策略轮询和 WebSocket'
    return
  }
  readableSummaryPaused.value = false
  fetchStatus()
  fetchRealtime()
  fetchMetrics()
  fetchCarbonWall()
  fetchControlPanel()
  fetchNilmEvents()
  fetchReadableSummary()
  startBackgroundPolling()
  message.value = '已退出控制维护模式：后台轮询和 WebSocket 已恢复'
}

function connectWebSocket() {
  if (ws) {
    ws.close()
    ws = null
  }
  const wsUrl = baseUrl.value.replace(/^http/, 'ws') + '/ws/realtime'
  ws = new WebSocket(wsUrl)
  ws.onopen = () => {
    wsConnected.value = true
  }
  ws.onmessage = (evt) => {
    try {
      const payload = JSON.parse(evt.data)
      if (payload?.realtime) {
        applyRealtimeRaw(payload.realtime, { co2_kg_per_hour: payload.co2_kg_per_hour })
        strategy.mode = payload?.strategy?.strategy_mode || 'rule+ai'
        strategy.power_step_w = payload?.strategy?.power_step_w ?? 0
        strategy.in_class_time = Boolean(payload?.strategy?.in_class_time)
        strategy.idle_duration_s = payload?.strategy?.idle_duration_s ?? 0
        strategy.auto_cutoff_triggered = Boolean(payload?.strategy?.auto_cutoff_triggered)
        backendOnline.value = true
        lastUpdate.value = Date.now()
      }
      if (payload?.control_ack) {
        controlPanel.last_ack = payload.control_ack
      }
    } catch (e) {
      // ignore parse errors
    }
  }
  ws.onclose = () => {
    wsConnected.value = false
  }
  ws.onerror = () => {
    wsConnected.value = false
  }
}

async function setControlMode(mode) {
  try {
    const res = await fetch(`${baseUrl.value}/api/control/mode?mode=${mode}`, { method: 'POST' })
    const payload = await res.json()
    if (!payload.success) throw new Error(payload.message || '模式切换失败')
    controlPanel.mode = payload.data?.mode || mode
    message.value = `模式切换成功：${controlPanel.mode}`
  } catch (err) {
    message.value = `模式切换失败：${err.message}`
  }
}

async function doControl(action) {
  const text = action === 'open' ? '分闸' : '合闸'
  const coilAddr = Number(controlPanel.selected_coil_addr ?? 3)
  const coilAddrHex = `0x${coilAddr.toString(16).toUpperCase().padStart(4, '0')}`
  const resumeReadableSummaryAfterControl = !readableSummaryPaused.value
  if (resumeReadableSummaryAfterControl) {
    readableSummaryPaused.value = true
    if (readableTimer) {
      clearInterval(readableTimer)
      readableTimer = null
    }
  }
  if (action === 'close' && controlPanel.mode === 'protect') {
    const allowSwitch = window.confirm('当前是保护模式，默认禁止合闸。是否先切换到手动模式再继续？')
    if (!allowSwitch) {
      if (resumeReadableSummaryAfterControl) {
        readableSummaryPaused.value = false
        startReadableSummaryPolling()
      }
      return
    }
    await setControlMode('manual')
  }
  if (!window.confirm(`确认对 ${coilAddrHex} 执行${text}吗？`)) {
    if (resumeReadableSummaryAfterControl) {
      readableSummaryPaused.value = false
      startReadableSummaryPolling()
    }
    return
  }
  try {
    const idempotencyKey = `${action}-${Date.now()}`
    const url = `${baseUrl.value}/api/control/${action}?operator=judge&source=dashboard&coil_addr=${encodeURIComponent(coilAddr)}&idempotency_key=${encodeURIComponent(idempotencyKey)}`
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 12000)
    const res = await fetch(url, { method: 'POST', signal: controller.signal })
    clearTimeout(timeoutId)
    const payload = await res.json()
    if (!payload.success) throw new Error(payload.message || `${text}失败`)
    controlPanel.last_ack = payload.data?.ack || null
    message.value = `${text}成功（${controlPanel.last_ack?.coil_addr_hex || coilAddrHex}），日志回执：${controlPanel.last_ack?.ack_id || '-'}`
  } catch (err) {
    if (err.name === 'AbortError') {
      message.value = `${text}超时：设备未在 12 秒内返回，请检查串口占用或设备是否接受该线圈地址`
      return
    }
    message.value = `${text}失败：${err.message}`
  } finally {
    if (resumeReadableSummaryAfterControl) {
      readableSummaryPaused.value = false
      fetchReadableSummary()
      startReadableSummaryPolling()
    }
  }
}

async function fetchRealtimeOnceForProbe() {
  const res = await fetch(`${baseUrl.value}/api/realtime`)
  const payload = await res.json()
  if (!payload.success) throw new Error(payload.message || '读取实时状态失败')
  return payload.data || {}
}

async function issueControl(action, coilAddr) {
  const idempotencyKey = `probe-${action}-${coilAddr}-${Date.now()}`
  const url = `${baseUrl.value}/api/control/${action}?operator=judge&source=probe&coil_addr=${encodeURIComponent(coilAddr)}&idempotency_key=${encodeURIComponent(idempotencyKey)}`
  const res = await fetch(url, { method: 'POST' })
  const payload = await res.json()
  if (!payload.success) {
    throw new Error(payload.message || `${action} failed`)
  }
  return payload.data?.ack || payload.data || {}
}

async function probeCoils() {
  if (probeRunning.value) return
  const confirmed = window.confirm('线圈巡检会依次对 0x0000 / 0x0001 / 0x0003 执行合闸再分闸，用于确认真实可控回路。是否继续？')
  if (!confirmed) return
  probeRunning.value = true
  probeResults.value = []
  const shouldRestorePolling = !maintenanceMode.value
  if (shouldRestorePolling) {
    maintenanceMode.value = true
    readableSummaryPaused.value = true
    stopBackgroundPolling()
    wsConnected.value = false
  }
  try {
    await setControlMode('manual')
    for (const coilAddr of [0, 1, 3]) {
      const coilAddrHex = `0x${coilAddr.toString(16).toUpperCase().padStart(4, '0')}`
      try {
        const closeAck = await issueControl('close', coilAddr)
        await new Promise((resolve) => setTimeout(resolve, 1600))
        const afterClose = await fetchRealtimeOnceForProbe()
        const openAck = await issueControl('open', coilAddr)
        await new Promise((resolve) => setTimeout(resolve, 1600))
        const afterOpen = await fetchRealtimeOnceForProbe()
        probeResults.value.push({
          coil_addr_hex: coilAddrHex,
          ok: true,
          closeAck,
          openAck,
          stateSummary: `close后:${afterClose.breaker_on ? 'on' : 'off'} / open后:${afterOpen.breaker_on ? 'on' : 'off'}`
        })
      } catch (err) {
        probeResults.value.push({
          coil_addr_hex: coilAddrHex,
          ok: false,
          stateSummary: err.message || '巡检失败'
        })
      }
    }
    message.value = '线圈巡检已完成，请查看“巡检结果”'
  } finally {
    probeRunning.value = false
    if (shouldRestorePolling) {
      maintenanceMode.value = false
      readableSummaryPaused.value = false
      fetchStatus()
      fetchRealtime()
      fetchMetrics()
      fetchCarbonWall()
      fetchControlPanel()
      fetchNilmEvents()
      fetchReadableSummary()
      startBackgroundPolling()
    }
  }
}

function updateClock() {
  nowTimeText.value = new Date().toLocaleString()
}

function startGuideAutoPlay() {
  if (guideTimer) clearInterval(guideTimer)
  guideTimer = setInterval(() => {
    if (!guideAutoPlay.value) return
    currentGuideIndex.value = (currentGuideIndex.value + 1) % defenseGuides.length
  }, 5000)
}

function toggleGuideAutoPlay() {
  guideAutoPlay.value = !guideAutoPlay.value
}

async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen()
      isFullscreen.value = true
    } else {
      await document.exitFullscreen()
      isFullscreen.value = false
    }
  } catch (e) {
    // ignore fullscreen errors
  }
}

async function scanDevice() {
  loading.value = true
  try {
    const res = await fetch(`${baseUrl.value}/api/scan`)
    const data = await res.json()

    if (data.success) {
      backendOnline.value = true
      message.value = data.message || '扫描成功'
      applyRealtimeData(data)
    } else {
      backendOnline.value = false
      message.value = data.message || '扫描失败'
    }
  } catch (err) {
    backendOnline.value = false
    message.value = `扫描请求失败：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  updateClock()
  fetchStatus()
  fetchRealtime()
  fetchMetrics()
  fetchCarbonWall()
  fetchControlPanel()
  fetchNilmEvents()
  fetchReadableSummary()
  connectWebSocket()
  startBackgroundPolling()
  clockTimer = setInterval(updateClock, 1000)
  startGuideAutoPlay()
  document.addEventListener('fullscreenchange', () => {
    isFullscreen.value = Boolean(document.fullscreenElement)
  })
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (metricsTimer) clearInterval(metricsTimer)
  if (readableTimer) clearInterval(readableTimer)
  if (carbonTimer) clearInterval(carbonTimer)
  if (controlTimer) clearInterval(controlTimer)
  if (nilmTimer) clearInterval(nilmTimer)
  if (clockTimer) clearInterval(clockTimer)
  if (guideTimer) clearInterval(guideTimer)
  if (ws) ws.close()
})

const chartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['功率(W)', '电流(A)', '电压(V)'] },
  grid: { left: 36, right: 24, top: 40, bottom: 26 },
  xAxis: { type: 'category', data: trend.labels, boundaryGap: false },
  yAxis: { type: 'value' },
  series: [
    { name: '功率(W)', type: 'line', smooth: true, data: trend.power },
    { name: '电流(A)', type: 'line', smooth: true, data: trend.current },
    { name: '电压(V)', type: 'line', smooth: true, data: trend.voltage }
  ]
}))
</script>

<style scoped>
* { box-sizing: border-box; }

.app {
  position: relative;
  min-height: 100vh;
  padding: 24px;
  color: #e2e8f0;
  background: radial-gradient(circle at 20% 0%, #1f2a52 0%, #0b1022 40%, #040711 100%);
  overflow: hidden;
}

.bg-glow {
  position: absolute;
  width: 420px;
  height: 420px;
  border-radius: 999px;
  filter: blur(80px);
  z-index: 0;
  pointer-events: none;
}
.bg-glow-1 { top: -130px; left: -80px; background: rgba(43, 146, 255, 0.32); }
.bg-glow-2 { right: -100px; top: 240px; background: rgba(17, 255, 223, 0.2); }

.container {
  position: relative;
  z-index: 2;
  max-width: 1380px;
  margin: 0 auto;
}

.defense-topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  margin-bottom: 14px;
  border-radius: 14px;
  background: linear-gradient(120deg, rgba(30, 64, 175, 0.35), rgba(8, 47, 73, 0.35));
  border: 1px solid rgba(125, 211, 252, 0.35);
}

.defense-title {
  font-size: 16px;
  font-weight: 700;
  color: #e0f2fe;
  margin-bottom: 4px;
}

.defense-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: #bfdbfe;
  font-size: 12px;
}

.defense-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.clock {
  font-size: 13px;
  color: #dbeafe;
  font-weight: 600;
}

.ghost-btn {
  background: rgba(15, 23, 42, 0.45);
  border: 1px solid rgba(148, 163, 184, 0.45);
  color: #e2e8f0;
}

.header { margin-bottom: 20px; }
.header-kicker {
  margin: 0 0 8px;
  letter-spacing: 1.6px;
  font-size: 12px;
  color: #60a5fa;
  text-transform: uppercase;
}
.header h1 {
  margin: 0;
  font-size: 36px;
  font-weight: 800;
  line-height: 1.25;
  color: #f8fafc;
}
.subtitle {
  margin-top: 10px;
  color: #9fb1d1;
  font-size: 14px;
}
.headline-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}
.tag-chip {
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.18);
  border: 1px solid rgba(96, 165, 250, 0.4);
  color: #dbeafe;
  font-size: 12px;
}

.toolbar,
.status-bar,
.panel,
.card {
  background: linear-gradient(155deg, rgba(16, 24, 48, 0.82), rgba(12, 18, 38, 0.86));
  border: 1px solid rgba(148, 163, 184, 0.2);
  box-shadow: 0 18px 36px rgba(3, 10, 28, 0.35);
  backdrop-filter: blur(6px);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  border-radius: 16px;
  padding: 14px 18px;
  margin-bottom: 14px;
}
.backend-config {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.backend-config label {
  white-space: nowrap;
  font-weight: 600;
  color: #cbd5e1;
}
.url-input {
  width: 100%;
  max-width: 420px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 10px;
  outline: none;
  color: #f8fafc;
  background: rgba(15, 23, 42, 0.85);
}
.url-input:focus {
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.25);
}

.btn-group { display: flex; gap: 10px; }
button {
  border: none;
  background: linear-gradient(135deg, #2563eb, #38bdf8);
  color: white;
  padding: 10px 16px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
button:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(59, 130, 246, 0.35);
}
button:disabled {
  background: linear-gradient(135deg, #64748b, #94a3b8);
  cursor: not-allowed;
}

.status-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px 14px;
  border-radius: 16px;
  padding: 14px 18px;
  margin-bottom: 16px;
}
.status-item {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  padding: 8px 10px;
  min-width: 160px;
}

.label { color: #93a4c5; margin-right: 6px; }
.ok { color: #22c55e; font-weight: 700; }
.error { color: #f87171; font-weight: 700; }

.message {
  padding: 12px 16px;
  border-radius: 12px;
  margin-bottom: 16px;
  font-size: 14px;
}
.success {
  background: rgba(22, 163, 74, 0.16);
  color: #86efac;
  border: 1px solid rgba(74, 222, 128, 0.35);
}
.error-box {
  background: rgba(220, 38, 38, 0.16);
  color: #fca5a5;
  border: 1px solid rgba(248, 113, 113, 0.35);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.card {
  border-radius: 16px;
  padding: 18px;
  min-height: 135px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.card:nth-child(1),
.card:nth-child(3),
.card:nth-child(7) {
  border-color: rgba(56, 189, 248, 0.45);
}
.card h3 {
  margin: 0 0 10px 0;
  color: #9fb1d1;
  font-size: 14px;
  font-weight: 600;
}
.value {
  font-size: 32px;
  font-weight: 800;
  color: #f8fafc;
  word-break: break-word;
  line-height: 1.15;
}
.unit {
  margin-top: 8px;
  color: #90a2c5;
  font-size: 12px;
}
.on { color: #22c55e; }
.off { color: #f87171; }

.panel {
  border-radius: 16px;
  padding: 18px;
  margin-bottom: 16px;
}
.panel h2 {
  margin-top: 0;
  margin-bottom: 14px;
  font-size: 18px;
  color: #e2e8f0;
}

.empty { color: #9fb1d1; }
.alarm-list { display: flex; flex-direction: column; gap: 10px; }
.alarm-item {
  border-left: 4px solid #ef4444;
  background: rgba(239, 68, 68, 0.1);
  padding: 10px 12px;
  border-radius: 10px;
}
.alarm-title { font-weight: 700; color: #fecaca; }
.alarm-msg { margin-top: 4px; color: #fca5a5; }
.alarm-time { margin-top: 6px; color: #fda4af; font-size: 12px; }

.raw-row {
  margin-bottom: 10px;
  line-height: 1.65;
  word-break: break-all;
  color: #d4dded;
}
.raw-label { color: #93a4c5; margin-right: 8px; font-weight: 600; }
.raw-response { font-family: Consolas, Monaco, monospace; }

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px 12px;
}
.metric-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(51, 65, 85, 0.42);
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.control-select {
  min-width: 150px;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.9);
  color: #e2e8f0;
}

.tag {
  display: inline-block;
  margin-right: 8px;
  margin-bottom: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.18);
  border: 1px solid rgba(125, 211, 252, 0.3);
  font-size: 12px;
  color: #dbeafe;
}

.quality-badge {
  display: inline-block;
  width: fit-content;
  margin-top: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(250, 204, 21, 0.18);
  border: 1px solid rgba(250, 204, 21, 0.35);
  color: #fde68a;
  font-size: 12px;
}

.chart-panel {
  border: 1px solid rgba(34, 211, 238, 0.3);
}
.chart {
  width: 100%;
  height: 400px;
}

.defense-guide-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.defense-guide-card {
  background: rgba(30, 41, 59, 0.42);
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 12px;
  padding: 14px;
}

.guide-step {
  color: #7dd3fc;
  font-size: 12px;
  margin-bottom: 6px;
}

.guide-title {
  font-size: 18px;
  font-weight: 700;
  color: #f8fafc;
  margin-bottom: 6px;
}

.guide-text {
  color: #cbd5e1;
  line-height: 1.7;
}

@media (max-width: 768px) {
  .app { padding: 14px; }
  .header h1 { font-size: 26px; }
  .defense-topbar {
    flex-direction: column;
    align-items: flex-start;
  }
  .defense-right {
    width: 100%;
    justify-content: space-between;
  }
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .backend-config {
    flex-direction: column;
    align-items: flex-start;
  }
  .url-input { max-width: 100%; }
  .btn-group { width: 100%; }
  .btn-group button { flex: 1; }
  .value { font-size: 27px; }
  .chart { height: 320px; }
}
</style>