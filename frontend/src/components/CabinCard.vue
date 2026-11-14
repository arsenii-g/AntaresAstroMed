<script setup>
// Cabina: color con `systems.environment` (③) y números en vivo de `cabin` (①).
import { computed } from 'vue'
import { levelInfo } from '@/levels'
import { fmt } from '@/format'

const props = defineProps({
  environment: { type: Object, default: null },
  cabin: { type: Object, default: null },
})
const info = computed(() => levelInfo(props.environment?.level ?? null))
</script>

<template>
  <section class="card cabin" :style="{ borderColor: info.color }">
    <header class="card-head">
      <h2>Cabin</h2>
      <span class="pill" :style="{ background: info.color, color: info.ink }">{{ info.title }}</span>
    </header>
    <dl class="stats">
      <div><dt>Temperature</dt><dd>{{ fmt(cabin?.temp_c, '°C', 1) }}</dd></div>
      <div><dt>Humidity</dt><dd>{{ fmt(cabin?.humidity_pct, '%') }}</dd></div>
      <div><dt>Heat index</dt><dd>{{ fmt(cabin?.heat_index_c, '°C', 1) }}</dd></div>
      <div><dt>Dew point</dt><dd>{{ fmt(cabin?.dew_point_c, '°C', 1) }}</dd></div>
      <div><dt>Condensation</dt><dd>{{ cabin?.condensation_risk ?? '—' }}</dd></div>
    </dl>
    <ul v-if="environment?.reasons?.length" class="reasons">
      <li v-for="(r, i) in environment.reasons" :key="i">{{ r }}</li>
    </ul>
  </section>
</template>

<style scoped>
.cabin {
  border-left-width: 6px;
}
.reasons {
  margin: 0.6rem 0 0;
  padding-left: 1.25rem;
  font-size: 0.9rem;
}
</style>
