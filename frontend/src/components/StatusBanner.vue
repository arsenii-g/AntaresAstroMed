<script setup>
// Aviso grande con el nivel global: "All clear" verde, "Caution" ámbar,
// "Warning" naranja, "Alert!" rojo, "No data" gris.
import { computed } from 'vue'
import { levelInfo } from '@/levels'
import { fmtTime } from '@/format'

const props = defineProps({
  level: { type: Number, default: null },
  ts: { type: String, default: null },
})
const info = computed(() => levelInfo(props.level))
</script>

<template>
  <section
    class="banner"
    :class="`lvl-${info.key}`"
    :style="{ background: info.color, color: info.ink }"
    role="status"
    aria-live="polite"
  >
    <div class="title">{{ info.title }}</div>
    <div class="hint">{{ info.hint }}</div>
    <div v-if="ts" class="ts">Assessed at {{ fmtTime(ts) }}</div>
  </section>
</template>

<style scoped>
.banner {
  border-radius: var(--radius);
  padding: 1rem 1.25rem;
  transition: background 0.4s ease;
}
.title {
  font-size: 1.8rem;
  font-weight: 800;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.hint {
  font-size: 1rem;
  margin-top: 0.15rem;
}
.ts {
  font-size: 0.8rem;
  opacity: 0.8;
  margin-top: 0.4rem;
}
.lvl-red .title {
  animation: blink 1.4s steps(1) infinite;
}
@keyframes blink {
  50% { opacity: 0.55; }
}
@media (prefers-reduced-motion: reduce) {
  .lvl-red .title { animation: none; }
}
</style>
