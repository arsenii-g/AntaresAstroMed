<script setup>
// Muñeco del tripulante. Cada zona se pinta con el nivel de su sistema (③):
//   cabeza → neuro · pecho → cardiovascular · brazos y piernas → musculoskeletal
// El halo de fondo lleva el color del nivel global, como el aviso.
// Si un sistema está en ámbar o peor, se resalta su órgano:
//   neuro → cerebro · cardiovascular → corazón · musculoskeletal → esqueleto
import { computed } from 'vue'
import { levelInfo, LEVELS, NO_DATA, SYSTEMS } from '@/levels'

const props = defineProps({
  systems: { type: Object, default: null },
  overall: { type: Number, default: null },
  selected: { type: String, default: null },
})
const emit = defineEmits(['select'])

const zone = computed(() => {
  const z = {}
  for (const s of ['neuro', 'cardiovascular', 'musculoskeletal']) {
    const info = levelInfo(props.systems?.[s]?.level ?? null)
    z[s] = { ...info, problem: info.level != null && info.level >= 1 }
  }
  return z
})
const overallInfo = computed(() => levelInfo(props.overall))

function fillOf(s) {
  return zone.value[s].level == null ? 'url(#body-nodata)' : zone.value[s].color
}

function toggle(s) {
  emit('select', props.selected === s ? null : s)
}

function zoneAttrs(s) {
  const z = zone.value[s]
  return {
    class: ['zone', `lvl-${z.key}`, { problem: z.problem, selected: props.selected === s }],
    style: { color: z.color },
    role: 'button',
    tabindex: 0,
    'aria-pressed': String(props.selected === s),
    'aria-label': `${SYSTEMS[s].zone}, ${SYSTEMS[s].label}: ${z.title}`,
    onClick: () => toggle(s),
    onKeydown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        toggle(s)
      }
    },
  }
}

const legend = [...Object.keys(LEVELS).map((l) => levelInfo(Number(l))), levelInfo(null)]
</script>

<template>
  <figure class="body-figure">
    <svg viewBox="0 0 220 440" class="body-svg" aria-label="Crew member body status">
      <defs>
        <pattern id="body-nodata" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" :style="{ fill: 'var(--lvl-none)' }" />
          <line x1="0" y1="0" x2="0" y2="8" class="hatch" />
        </pattern>
        <radialGradient id="body-halo">
          <stop offset="0%" :style="{ stopColor: overallInfo.color, stopOpacity: 0.35 }" />
          <stop offset="100%" :style="{ stopColor: overallInfo.color, stopOpacity: 0 }" />
        </radialGradient>
      </defs>

      <!-- Halo con el nivel global -->
      <ellipse cx="110" cy="225" rx="108" ry="215" fill="url(#body-halo)" />

      <!-- Brazos y piernas: musculoskeletal -->
      <g v-bind="zoneAttrs('musculoskeletal')">
        <title>{{ SYSTEMS.musculoskeletal.label }}: {{ zone.musculoskeletal.title }}</title>
        <g transform="rotate(10 48 104)">
          <rect class="part" x="36" y="104" width="24" height="132" rx="12" :style="{ fill: fillOf('musculoskeletal') }" />
        </g>
        <g transform="rotate(-10 172 104)">
          <rect class="part" x="160" y="104" width="24" height="132" rx="12" :style="{ fill: fillOf('musculoskeletal') }" />
        </g>
        <rect class="part" x="72" y="230" width="34" height="184" rx="15" :style="{ fill: fillOf('musculoskeletal') }" />
        <rect class="part" x="114" y="230" width="34" height="184" rx="15" :style="{ fill: fillOf('musculoskeletal') }" />

        <g v-if="zone.musculoskeletal.problem" class="organ skeleton" aria-hidden="true">
          <g transform="rotate(10 48 104)">
            <line x1="48" y1="114" x2="48" y2="164" /><circle cx="48" cy="170" r="4" /><line x1="48" y1="176" x2="48" y2="226" />
          </g>
          <g transform="rotate(-10 172 104)">
            <line x1="172" y1="114" x2="172" y2="164" /><circle cx="172" cy="170" r="4" /><line x1="172" y1="176" x2="172" y2="226" />
          </g>
          <line x1="89" y1="244" x2="89" y2="316" /><circle cx="89" cy="323" r="5" /><line x1="89" y1="330" x2="89" y2="402" />
          <line x1="131" y1="244" x2="131" y2="316" /><circle cx="131" cy="323" r="5" /><line x1="131" y1="330" x2="131" y2="402" />
        </g>
      </g>

      <!-- Tronco: cardiovascular -->
      <g v-bind="zoneAttrs('cardiovascular')">
        <title>{{ SYSTEMS.cardiovascular.label }}: {{ zone.cardiovascular.title }}</title>
        <rect class="part" x="98" y="80" width="24" height="22" rx="6" :style="{ fill: fillOf('cardiovascular') }" />
        <path
          class="part"
          d="M66 102 Q110 92 154 102 L160 214 Q152 242 110 244 Q68 242 60 214 Z"
          :style="{ fill: fillOf('cardiovascular') }"
        />
        <g v-if="zone.cardiovascular.problem" class="organ heart" aria-hidden="true">
          <path
            transform="translate(112 126) scale(1.5)"
            d="M12 21 C5 15 0 11 0 6 C0 2.5 2.7 0 6 0 C8.4 0 10.6 1.4 12 3.4 C13.4 1.4 15.6 0 18 0 C21.3 0 24 2.5 24 6 C24 11 19 15 12 21 Z"
          />
        </g>
      </g>

      <!-- Cabeza: neuro -->
      <g v-bind="zoneAttrs('neuro')">
        <title>{{ SYSTEMS.neuro.label }}: {{ zone.neuro.title }}</title>
        <circle class="part" cx="110" cy="50" r="34" :style="{ fill: fillOf('neuro') }" />
        <g v-if="zone.neuro.problem" class="organ brain" aria-hidden="true">
          <path d="M110 30 C96 26 86 34 88 44 C82 48 84 60 92 62 C94 70 104 72 110 66 C116 72 126 70 128 62 C136 60 138 48 132 44 C134 34 124 26 110 30 Z" />
          <path class="fold" d="M110 31 V65 M96 40 Q102 44 98 50 M124 40 Q118 44 122 50 M94 56 Q100 54 104 58 M126 56 Q120 54 116 58" />
        </g>
      </g>
    </svg>

    <figcaption class="legend">
      <span v-for="l in legend" :key="l.key" class="legend-item">
        <span class="dot" :class="{ hatched: l.level == null }" :style="{ background: l.color }" />{{ l.name }}
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.body-figure {
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.body-svg {
  width: 100%;
  max-width: 300px;
  height: auto;
  overflow: visible;
}
.zone {
  cursor: pointer;
  outline: none;
}
.part {
  stroke: var(--body-stroke);
  stroke-width: 2;
  transition: fill 0.4s ease, stroke 0.2s ease;
}
.zone:hover .part,
.zone:focus-visible .part {
  stroke: var(--fg);
  stroke-width: 3;
}
.zone.selected .part {
  stroke: var(--fg);
  stroke-width: 4;
}
/* El órgano resaltado brilla con el color de su nivel (currentColor). */
.zone.problem {
  filter: drop-shadow(0 0 6px currentColor);
}
.zone.lvl-red.problem {
  animation: pulse-glow 1.2s ease-in-out infinite;
}
.organ {
  pointer-events: none;
}
.organ path,
.organ circle {
  fill: var(--organ-fill);
  stroke: var(--organ-stroke);
  stroke-width: 1.5;
}
.organ .fold {
  fill: none;
}
.skeleton line {
  stroke: var(--organ-fill);
  stroke-width: 6;
  stroke-linecap: round;
}
.heart path {
  fill: #fff;
  transform-box: fill-box;
  transform-origin: center;
}
.lvl-orange .heart,
.lvl-red .heart {
  animation: beat 0.9s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}
.hatch {
  stroke: #fff;
  stroke-opacity: 0.35;
  stroke-width: 3;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.4rem 0.9rem;
  font-size: 0.8rem;
  color: var(--muted);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.dot {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 50%;
  display: inline-block;
}
.dot.hatched {
  background-image: repeating-linear-gradient(45deg, transparent 0 2px, rgba(255, 255, 255, 0.4) 2px 4px) !important;
}
@keyframes beat {
  0%, 100% { transform: scale(1); }
  30% { transform: scale(1.15); }
}
@keyframes pulse-glow {
  0%, 100% { filter: drop-shadow(0 0 4px currentColor); }
  50% { filter: drop-shadow(0 0 14px currentColor); }
}
@media (prefers-reduced-motion: reduce) {
  .zone, .heart, .lvl-red.problem { animation: none !important; }
}
</style>
