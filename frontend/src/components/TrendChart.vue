<script setup>
// Una tendencia de 7 días: la recta del motor, la línea de umbral con el color
// del nivel al que llevaría y el punto donde la cruza.
import { computed, ref } from 'vue'
import { HORIZON_DAYS, indicatorInfo, trendLine } from '@/trends'
import { levelInfo } from '@/levels'
import { fmt } from '@/format'

const props = defineProps({ trend: { type: Object, required: true } })

const W = 340
const H = 160
const M = { top: 14, right: 14, bottom: 26, left: 44 }
const PW = W - M.left - M.right
const PH = H - M.top - M.bottom

const info = computed(() => indicatorInfo(props.trend.indicator))
const line = computed(() => trendLine(props.trend))
const threshold = computed(() => (props.trend.threshold == null ? null : Number(props.trend.threshold)))
const crossDays = computed(() => props.trend.crosses_threshold_in_days)
const thresholdInfo = computed(() => levelInfo(props.trend.threshold_level ?? null))

// Dominio Y: la recta en −7, 0, +7 y el umbral, con un poco de aire.
const yDomain = computed(() => {
  const vals = [line.value(-HORIZON_DAYS), line.value(0), line.value(HORIZON_DAYS)]
  if (threshold.value != null) vals.push(threshold.value)
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  const pad = Math.max((hi - lo) * 0.15, Math.abs(hi) * 0.02, 0.5)
  lo -= pad
  hi += pad
  if (info.value.min != null) lo = Math.max(info.value.min - 0.2, lo)
  if (info.value.max != null) hi = Math.min(info.value.max + 0.2, hi)
  return [lo, hi]
})

const x = (d) => M.left + ((d + HORIZON_DAYS) / (2 * HORIZON_DAYS)) * PW
const y = (v) => {
  const [lo, hi] = yDomain.value
  return M.top + (1 - (v - lo) / (hi - lo)) * PH
}

const yTicks = computed(() => {
  const [lo, hi] = yDomain.value
  const step = niceStep((hi - lo) / 3)
  const ticks = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(6))
  return ticks
})
const xTicks = [-7, -3.5, 0, 3.5, 7]

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw))
  const n = raw / p
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p
}

const fmtV = (v) => fmt(v, '', info.value.digits)
const dayLabel = (d) => (d === 0 ? 'Today' : `${d > 0 ? '+' : '−'}${Math.abs(d)} d`)

const pastPath = computed(() => `M${x(-HORIZON_DAYS)},${y(line.value(-HORIZON_DAYS))} L${x(0)},${y(line.value(0))}`)
const futurePath = computed(() => `M${x(0)},${y(line.value(0))} L${x(HORIZON_DAYS)},${y(line.value(HORIZON_DAYS))}`)

const headline = computed(() => {
  if (crossDays.value != null && threshold.value != null)
    return `Reaches ${fmtV(threshold.value)} ${info.value.unit} (${thresholdInfo.value.name}) in ${crossDays.value} days`
  return 'No threshold crossed within 7 days'
})
const slopeText = computed(() => {
  const s = Number(props.trend.slope_per_day)
  return `${s > 0 ? '+' : s < 0 ? '−' : '±'}${Math.abs(s)} ${info.value.unit}/day`
})

// Capa de hover: cruceta y tooltip con el valor de la recta en ese día.
const hover = ref(null)
function onMove(e) {
  const svg = e.currentTarget.ownerSVGElement
  const pt = svg.createSVGPoint()
  pt.x = e.clientX
  pt.y = e.clientY
  const local = pt.matrixTransform(svg.getScreenCTM().inverse())
  const d = Math.round((((local.x - M.left) / PW) * 2 * HORIZON_DAYS - HORIZON_DAYS) * 2) / 2
  const day = Math.max(-HORIZON_DAYS, Math.min(HORIZON_DAYS, d))
  hover.value = { day, value: line.value(day) }
}
</script>

<template>
  <figure class="trend">
    <figcaption>
      <div class="name">{{ info.label }}</div>
      <div class="headline" :class="{ warn: crossDays != null }">
        <span v-if="crossDays != null" class="swatch" :style="{ background: thresholdInfo.color }" aria-hidden="true" />
        {{ headline }}
      </div>
      <div class="meta">
        In 7 days: <strong>{{ fmtV(trend.projected_7d) }} {{ info.unit }}</strong> · {{ slopeText }}
      </div>
    </figcaption>

    <div class="plot">
      <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="`${info.label}: ${headline}. Projected ${fmtV(trend.projected_7d)} ${info.unit} in 7 days.`">
        <!-- Rejilla y ejes, recesivos -->
        <g class="grid">
          <line v-for="v in yTicks" :key="v" :x1="M.left" :x2="W - M.right" :y1="y(v)" :y2="y(v)" />
        </g>
        <g class="axis">
          <text v-for="v in yTicks" :key="'y' + v" :x="M.left - 6" :y="y(v)" text-anchor="end" dominant-baseline="middle">{{ fmtV(v) }}</text>
          <text v-for="d in xTicks" :key="'x' + d" :x="x(d)" :y="H - 8" text-anchor="middle">{{ dayLabel(d) }}</text>
        </g>

        <!-- Fondo de la zona futura -->
        <rect class="future-bg" :x="x(0)" :y="M.top" :width="x(HORIZON_DAYS) - x(0)" :height="PH" />
        <line class="today" :x1="x(0)" :x2="x(0)" :y1="M.top" :y2="M.top + PH" />

        <!-- Umbral -->
        <g v-if="threshold != null">
          <line class="threshold" :x1="M.left" :x2="W - M.right" :y1="y(threshold)" :y2="y(threshold)" :style="{ stroke: thresholdInfo.color }" />
          <text class="threshold-label" :x="W - M.right - 2" :y="y(threshold) - 5" text-anchor="end">
            {{ thresholdInfo.name }} · {{ fmtV(threshold) }}
          </text>
        </g>

        <!-- Recta: ajuste (pasado) y proyección (futuro) -->
        <path class="fit" :d="pastPath" />
        <path class="projection" :d="futurePath" />
        <circle class="now-dot" :cx="x(0)" :cy="y(line(0))" r="4" />

        <!-- Cruce del umbral -->
        <circle
          v-if="crossDays != null && threshold != null"
          class="cross"
          :cx="x(crossDays)"
          :cy="y(threshold)"
          r="5.5"
          :style="{ fill: thresholdInfo.color }"
        />

        <!-- Hover -->
        <g v-if="hover" class="crosshair">
          <line :x1="x(hover.day)" :x2="x(hover.day)" :y1="M.top" :y2="M.top + PH" />
          <circle :cx="x(hover.day)" :cy="y(hover.value)" r="4" />
        </g>
        <rect
          class="hit"
          :x="M.left"
          :y="M.top"
          :width="PW"
          :height="PH"
          @pointermove="onMove"
          @pointerdown="onMove"
          @pointerleave="hover = null"
        />
      </svg>
      <div
        v-if="hover"
        class="tooltip"
        :style="{ left: `${(x(hover.day) / W) * 100}%`, top: `${(y(hover.value) / H) * 100}%` }"
        role="status"
      >
        <div class="tt-day">{{ dayLabel(hover.day) }} · {{ hover.day > 0 ? 'projected' : hover.day < 0 ? '7-day fit' : 'now (fit)' }}</div>
        <div class="tt-val">{{ fmtV(hover.value) }} {{ info.unit }}</div>
      </div>
    </div>
  </figure>
</template>

<style scoped>
.trend {
  margin: 0;
  min-width: 0;
}
.name {
  font-weight: 700;
}
.headline {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9rem;
  color: var(--muted);
}
.headline.warn {
  color: var(--fg);
  font-weight: 600;
}
.swatch {
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 2px;
  flex: none;
}
.meta {
  font-size: 0.8rem;
  color: var(--muted);
  margin-top: 0.1rem;
}
.plot {
  position: relative;
  margin-top: 0.4rem;
}
svg {
  width: 100%;
  height: auto;
  display: block;
  overflow: visible;
}
.grid line {
  stroke: var(--line);
  stroke-width: 1;
}
.axis text {
  fill: var(--muted);
  font-size: 10px;
}
.future-bg {
  fill: var(--fg);
  opacity: 0.04;
}
.today {
  stroke: var(--muted);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.threshold {
  stroke-width: 2;
  stroke-dasharray: 6 4;
}
.threshold-label {
  fill: var(--fg);
  font-size: 10px;
  font-weight: 600;
}
.fit,
.projection {
  fill: none;
  stroke: var(--accent);
  stroke-width: 2;
  stroke-linecap: round;
}
.projection {
  stroke-dasharray: 5 4;
}
.now-dot {
  fill: var(--accent);
  stroke: var(--surface);
  stroke-width: 2;
}
.cross {
  stroke: var(--surface);
  stroke-width: 2;
}
.crosshair line {
  stroke: var(--muted);
  stroke-width: 1;
}
.crosshair circle {
  fill: var(--surface);
  stroke: var(--accent);
  stroke-width: 2;
}
.hit {
  fill: transparent;
  cursor: crosshair;
}
.tooltip {
  position: absolute;
  transform: translate(-50%, calc(-100% - 10px));
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  white-space: nowrap;
  pointer-events: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
}
.tt-day {
  color: var(--muted);
}
.tt-val {
  font-weight: 700;
}
</style>
