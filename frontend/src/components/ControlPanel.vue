<template>
  <div class="card control-panel">
    <div class="panel-header">
      <h2>远程控制中心</h2>
      <span class="tag blue">硬件控制</span>
    </div>

    <div class="channel-picker">
      <span class="picker-label">控制路数</span>
      <div class="picker-buttons">
        <button
          v-for="channel in channels"
          :key="channel"
          class="channel-btn"
          :class="{ active: selectedChannel === channel }"
          @click="$emit('select-channel', channel)"
        >
          第{{ channel }}路
        </button>
      </div>
    </div>

    <div class="control-buttons">
      <button class="success-btn" @click="$emit('close-breaker')">合闸</button>
      <button class="danger-btn" @click="$emit('open-breaker')">分闸</button>
      <button class="warn-btn" @click="$emit('reset-alarm')">报警复位</button>
    </div>

    <div class="control-buttons strategy-row">
      <button @click="$emit('set-mode', '正常模式')">正常模式</button>
      <button @click="$emit('set-mode', '离校模式')">一键离校模式</button>
      <button @click="$emit('set-mode', '睡眠节能模式')">睡眠节能模式</button>
    </div>

    <div class="control-log">
      <h3>控制反馈</h3>
      <p>{{ message }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  message: {
    type: String,
    default: ''
  },
  selectedChannel: {
    type: Number,
    default: 1
  },
  channels: {
    type: Array,
    default: () => [1, 2, 4]
  }
})

defineEmits(['close-breaker', 'open-breaker', 'reset-alarm', 'set-mode', 'select-channel'])
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

.tag.blue {
  color: #bfdbfe;
  background: rgba(96, 165, 250, 0.15);
  border: 1px solid rgba(96, 165, 250, 0.25);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
}

.control-buttons {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.channel-picker {
  margin-bottom: 14px;
}

.picker-label {
  color: #93c5fd;
  font-size: 14px;
  margin-bottom: 8px;
  display: block;
}

.picker-buttons {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.channel-btn {
  background: #334155;
}

.channel-btn.active {
  background: #2563eb;
  border: 1px solid #60a5fa;
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
</style>