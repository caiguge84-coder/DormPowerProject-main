<template>
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
        <div class="mini-value">{{ stats.energy_kwh.toFixed(3) }} kWh</div>
      </div>

      <div class="mini-panel">
        <div class="mini-label">今日累计碳排</div>
        <div class="mini-value">{{ stats.co2_g.toFixed(2) }} g</div>
      </div>

      <div class="mini-panel">
        <div class="mini-label">等效植树</div>
        <div class="mini-value">{{ stats.tree_equivalent.toFixed(3) }} 棵</div>
      </div>

      <div class="mini-panel">
        <div class="mini-label">当前模式</div>
        <div class="mini-value">{{ mode }}</div>
      </div>

      <div class="mini-panel">
        <div class="mini-label">告警状态</div>
        <div class="mini-value" :class="alarmCount ? 'text-danger' : 'text-ok'">
          {{ alarmCount ? '存在告警' : '运行正常' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  realtime: {
    type: Object,
    required: true
  },
  stats: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: '正常模式'
  },
  alarmCount: {
    type: Number,
    default: 0
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

@media (max-width: 900px) {
  .monitor-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 700px) {
  .monitor-grid {
    grid-template-columns: 1fr;
  }
}
</style>