<script setup>
// Números en vivo de la telemetría (①). Sin colores: los niveles son del motor.
import { fmt, fmtTime } from '@/format'

defineProps({
  telemetry: { type: Object, default: null },
  exercise: { type: Object, default: null },
})
</script>

<template>
  <section class="card">
    <header class="card-head">
      <h2>Live readings</h2>
      <span class="muted small">{{ telemetry ? fmtTime(telemetry.ts) : 'waiting…' }}</span>
    </header>
    <dl class="stats">
      <div>
        <dt>Heart rate</dt>
        <dd>{{ fmt(telemetry?.vitals?.heart_rate_bpm, 'bpm') }}</dd>
      </div>
      <div>
        <dt>Body temp.</dt>
        <dd>{{ fmt(telemetry?.vitals?.body_temp_c, '°C', 1) }}</dd>
      </div>
      <div>
        <dt>Activity</dt>
        <dd>
          {{ telemetry?.motion?.activity ?? '—' }}
          <span v-if="telemetry?.motion?.activity === 'still'" class="muted small">({{ fmt(telemetry.motion.still_for_s, 's') }})</span>
        </dd>
      </div>
      <div>
        <dt>Last push-ups</dt>
        <dd>{{ exercise ? `${exercise.data?.reps ?? '—'} reps` : '—' }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.small {
  font-size: 0.8rem;
}
</style>
