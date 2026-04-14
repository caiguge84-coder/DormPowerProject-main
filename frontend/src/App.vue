<template>
  <div class="app">
    <div class="container">
      <header class="header">
        <h1>宿舍用电监测系统</h1>
        <p class="subtitle">基于 RS485 / Modbus RTU 的智能空开实时监测</p>
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
          <div class="unit">W</div>
        </div>

        <div class="card">
          <h3>线路电流</h3>
          <div class="value">{{ formatNumber(realtime.current_a) }}</div>
          <div class="unit">A</div>
        </div>

        <div class="card">
          <h3>模块温度</h3>
          <div class="value">{{ formatNumber(realtime.temperature_c) }}</div>
          <div class="unit">℃</div>
        </div>

        <div class="card">
          <h3>漏电电流</h3>
          <div class="value">{{ formatNumber(realtime.leakage_current_ma) }}</div>
          <div class="unit">mA</div>
        </div>

        <div class="card">
          <h3>累计电量</h3>
          <div class="value">{{ formatNumber(realtime.energy_kwh) }}</div>
          <div class="unit">kWh</div>
        </div>

        <div class="card">
          <h3>实时碳排</h3>
          <div class="value">{{ formatNumber(realtime.co2_emission_g_s) }}</div>
          <div class="unit">g/s</div>
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
        <h2>告警信息</h2>
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
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'

const baseUrl = ref('http://127.0.0.1:8000')

const loading = ref(false)
const backendOnline = ref(false)
const message = ref('')

const port = ref('')
const baudrate = ref('')
const slaveId = ref('')
const lastUpdate = ref(null)

const alarms = ref([])

const realtime = reactive({
  frame_type: '',
  raw_response: '',
  raw_registers: [],
  voltage_v: 0,
  leakage_current_ma: 0,
  power_w: 0,
  temperature_c: 0,
  current_a: 0,
  alarm_status: 0,
  energy_kwh: 0,
  breaker_on: false,
  co2_emission_g_s: 0,
  timestamp: 0
})

let timer = null

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

function applyRealtimeData(res) {
  port.value = res.port ?? ''
  baudrate.value = res.baudrate ?? ''
  slaveId.value = res.slave_id ?? ''
  alarms.value = Array.isArray(res.alarms) ? res.alarms : []

  const d = res.data || {}

  realtime.frame_type = d.frame_type || ''
  realtime.raw_response = d.raw_response || ''
  realtime.raw_registers = Array.isArray(d.raw_registers) ? d.raw_registers : []
  realtime.voltage_v = d.voltage_v ?? 0
  realtime.leakage_current_ma = d.leakage_current_ma ?? 0
  realtime.power_w = d.power_w ?? 0
  realtime.temperature_c = d.temperature_c ?? 0
  realtime.current_a = d.current_a ?? 0
  realtime.alarm_status = d.alarm_status ?? 0
  realtime.energy_kwh = d.energy_kwh ?? 0
  realtime.breaker_on = !!d.breaker_on
  realtime.co2_emission_g_s = d.co2_emission_g_s ?? 0
  realtime.timestamp = d.timestamp ?? 0

  lastUpdate.value = Date.now()
}

async function fetchRealtime() {
  loading.value = true
  try {
    const res = await fetch(`${baseUrl.value}/api/realtime`)
    const data = await res.json()

    if (data.success) {
      backendOnline.value = true
      message.value = '实时数据读取成功'
      applyRealtimeData(data)
    } else {
      backendOnline.value = false
      message.value = data.message || '读取失败'
    }
  } catch (err) {
    backendOnline.value = false
    message.value = `请求失败：${err.message}`
  } finally {
    loading.value = false
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
  fetchRealtime()
  timer = setInterval(fetchRealtime, 2000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
* {
  box-sizing: border-box;
}

.app {
  min-height: 100vh;
  background: #f5f7fb;
  padding: 24px;
  color: #1f2937;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
}

.header {
  margin-bottom: 24px;
}

.header h1 {
  margin: 0;
  font-size: 32px;
  color: #111827;
}

.subtitle {
  margin-top: 8px;
  color: #6b7280;
  font-size: 14px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  background: white;
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
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
}

.url-input {
  width: 100%;
  max-width: 360px;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  outline: none;
}

.url-input:focus {
  border-color: #2563eb;
}

.btn-group {
  display: flex;
  gap: 12px;
}

button {
  border: none;
  background: #2563eb;
  color: white;
  padding: 10px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}

button:hover {
  background: #1d4ed8;
}

button:disabled {
  background: #93c5fd;
  cursor: not-allowed;
}

.status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  background: white;
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.status-item {
  min-width: 160px;
}

.label {
  color: #6b7280;
  margin-right: 6px;
}

.ok {
  color: #16a34a;
  font-weight: 700;
}

.error {
  color: #dc2626;
  font-weight: 700;
}

.message {
  padding: 14px 16px;
  border-radius: 12px;
  margin-bottom: 16px;
  font-size: 14px;
}

.success {
  background: #ecfdf5;
  color: #166534;
  border: 1px solid #a7f3d0;
}

.error-box {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.card {
  background: white;
  border-radius: 16px;
  padding: 22px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  min-height: 150px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.card h3 {
  margin: 0 0 14px 0;
  color: #6b7280;
  font-size: 15px;
  font-weight: 600;
}

.value {
  font-size: 34px;
  font-weight: 800;
  color: #111827;
  word-break: break-word;
}

.unit {
  margin-top: 8px;
  color: #9ca3af;
  font-size: 13px;
}

.on {
  color: #16a34a;
}

.off {
  color: #dc2626;
}

.panel {
  background: white;
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.panel h2 {
  margin-top: 0;
  margin-bottom: 16px;
  font-size: 20px;
}

.empty {
  color: #6b7280;
}

.alarm-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.alarm-item {
  border-left: 4px solid #ef4444;
  background: #fef2f2;
  padding: 12px 14px;
  border-radius: 10px;
}

.alarm-title {
  font-weight: 700;
  color: #991b1b;
}

.alarm-msg {
  margin-top: 6px;
  color: #7f1d1d;
}

.alarm-time {
  margin-top: 6px;
  color: #b91c1c;
  font-size: 12px;
}

.raw-row {
  margin-bottom: 12px;
  line-height: 1.7;
  word-break: break-all;
}

.raw-label {
  color: #6b7280;
  margin-right: 8px;
  font-weight: 600;
}

.raw-response {
  font-family: Consolas, Monaco, monospace;
}

@media (max-width: 768px) {
  .app {
    padding: 14px;
  }

  .header h1 {
    font-size: 24px;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .backend-config {
    flex-direction: column;
    align-items: flex-start;
  }

  .url-input {
    max-width: 100%;
  }

  .btn-group {
    width: 100%;
  }

  .btn-group button {
    flex: 1;
  }

  .value {
    font-size: 28px;
  }
}
</style>