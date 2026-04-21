<template>
  <div class="card metric-card" :class="variant">
    <div class="card-title">{{ title }}</div>
    <div class="metric-value" :class="{ pulse }">{{ value }}</div>
    <div class="metric-unit">{{ unit }}</div>
  </div>
</template>

<script setup>
defineProps({
  title: String,
  value: [String, Number],
  unit: String,
  pulse: {
    type: Boolean,
    default: false
  },
  variant: {
    type: String,
    default: ''
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
</style>