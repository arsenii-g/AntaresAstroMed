<script setup>
// Gráficas de tendencia (③ `trends`). Primero las que cruzan un umbral, antes las más cercanas.
import { computed } from 'vue'
import TrendChart from './TrendChart.vue'

const props = defineProps({ trends: { type: Array, default: () => [] } })

const sorted = computed(() =>
  [...props.trends].sort((a, b) => (a.crosses_threshold_in_days ?? Infinity) - (b.crosses_threshold_in_days ?? Infinity)),
)
</script>

<template>
  <section class="card">
    <header class="card-head">
      <h2>7-day trends</h2>
      <span class="muted key">
        <span class="k solid" />fit <span class="k dashed" />projection
      </span>
    </header>
    <p v-if="!sorted.length" class="muted">
      Not enough data yet. A trend needs at least 3 readings spread over a day or more.
    </p>
    <div v-else class="charts">
      <TrendChart v-for="t in sorted" :key="t.indicator" :trend="t" />
    </div>
  </section>
</template>

<style scoped>
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1.25rem;
}
.key {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
}
.k {
  display: inline-block;
  width: 1.4rem;
  height: 0;
  border-top: 2px solid var(--accent);
  margin-left: 0.4rem;
}
.k.dashed {
  border-top-style: dashed;
}
</style>
