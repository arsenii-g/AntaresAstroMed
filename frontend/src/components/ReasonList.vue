<script setup>
// Lista de problemas: los `reasons` de cada sistema, en inglés y tal cual.
// Si se ha pulsado una zona del cuerpo, solo se muestran los de ese sistema.
import { computed } from 'vue'
import { BODY_SYSTEMS, levelInfo, severity, SYSTEMS } from '@/levels'

const props = defineProps({
  systems: { type: Object, default: null },
  selected: { type: String, default: null },
})
const emit = defineEmits(['clear'])

const groups = computed(() => {
  // La cabina tiene su propia tarjeta; aquí solo van los sistemas del cuerpo.
  const keys = props.selected ? [props.selected] : BODY_SYSTEMS
  return keys
    .map((key) => {
      const s = props.systems?.[key]
      return { key, ...SYSTEMS[key], info: levelInfo(s?.level ?? null), reasons: s?.reasons ?? [] }
    })
    .filter((g) => props.selected || g.reasons.length)
    .sort((a, b) => severity(b.info.level) - severity(a.info.level))
})
</script>

<template>
  <section class="card">
    <header class="card-head">
      <h2>Problems</h2>
      <button v-if="selected" class="link" @click="emit('clear')">Show all</button>
    </header>

    <p v-if="!systems" class="muted">Waiting for the first assessment…</p>
    <p v-else-if="!groups.length" class="muted">No problems detected.</p>

    <div v-for="g in groups" :key="g.key" class="group">
      <h3>
        <span class="dot" :style="{ background: g.info.color }" />
        {{ g.label }} <span class="muted">· {{ g.info.title }}</span>
      </h3>
      <p v-if="selected" class="muted small">Measures: {{ g.measures }}</p>
      <ul v-if="g.reasons.length">
        <li v-for="(r, i) in g.reasons" :key="i">{{ r }}</li>
      </ul>
      <p v-else class="muted small">{{ g.info.level == null ? 'No data for this system.' : 'Nothing out of range.' }}</p>
    </div>
  </section>
</template>

<style scoped>
.group + .group {
  margin-top: 0.75rem;
}
h3 {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.95rem;
  margin: 0 0 0.3rem;
}
ul {
  margin: 0;
  padding-left: 1.5rem;
}
li + li {
  margin-top: 0.2rem;
}
.dot {
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  flex: none;
}
.small {
  font-size: 0.85rem;
  margin: 0.15rem 0;
}
</style>
