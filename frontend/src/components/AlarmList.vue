<template>
  <div class="card alarm-panel">
    <div class="panel-header">
      <h2>告警中心</h2>
      <span class="tag red">AI识别/规则告警</span>
    </div>

    <div v-if="alarms.length" class="alarm-list">
      <div v-for="item in alarms" :key="item.id" class="alarm-item">
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
</template>

<script setup>
defineProps({
  alarms: {
    type: Array,
    required: true
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

.tag.red {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.2);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
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
</style>