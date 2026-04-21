<template>
  <div class="card big-panel carbon-wall">
    <div class="panel-header">
      <h2>碳中和墙</h2>
      <span class="tag green">节能减排竞赛展示</span>
    </div>

    <div class="carbon-content">
      <div class="carbon-big">{{ stats.saved_co2_g.toFixed(2) }} g</div>
      <div class="carbon-desc">今日累计减排量</div>

      <div class="carbon-row">
        <div class="carbon-box">
          <div class="carbon-label">节电量</div>
          <div class="carbon-number">{{ stats.saved_energy_kwh.toFixed(3) }} kWh</div>
        </div>
        <div class="carbon-box">
          <div class="carbon-label">等效植树</div>
          <div class="carbon-number">{{ stats.tree_equivalent.toFixed(3) }}</div>
        </div>
      </div>

      <div class="tree-line">🌱 🌳 🌱 🌳 🌱</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  stats: {
    type: Object,
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
}

.tag.green {
  color: #86efac;
  background: rgba(34, 197, 94, 0.12);
  border: 1px solid rgba(34, 197, 94, 0.2);
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

@media (max-width: 700px) {
  .carbon-row {
    grid-template-columns: 1fr;
  }

  .carbon-big {
    font-size: 34px;
  }
}
</style>