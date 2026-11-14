<script setup>
// Pestaña "Status" del boceto: cuerpo a la izquierda; a la derecha, el aviso
// de color, la lista de problemas y la de recomendaciones.
import { computed, ref, watch } from 'vue'
import { useCrewState } from '@/stores/crewState'
import { levelInfo } from '@/levels'
import BodyFigure from '@/components/BodyFigure.vue'
import StatusBanner from '@/components/StatusBanner.vue'
import ReasonList from '@/components/ReasonList.vue'
import RecommendationList from '@/components/RecommendationList.vue'
import CabinCard from '@/components/CabinCard.vue'
import VitalsCard from '@/components/VitalsCard.vue'
import EarthSummary from '@/components/EarthSummary.vue'
import TrendPanel from '@/components/TrendPanel.vue'

const crew = useCrewState()
const selected = ref(null)
const assessment = computed(() => crew.assessment)
const overall = computed(() => assessment.value?.overall_level ?? null)

watch(() => crew.crewId, () => (selected.value = null))
</script>

<template>
  <div class="status-grid">
    <div class="col-body card">
      <BodyFigure
        :systems="assessment?.systems"
        :overall="overall"
        :selected="selected"
        @select="selected = $event"
      />
      <p class="muted hint">Tap a body zone to see its problems.</p>
    </div>

    <div class="col-panels">
      <p v-if="!crew.crewId" class="card waiting" role="status">
        Waiting for a crew member to scan their card. Nothing is shown until real data arrives.
      </p>
      <StatusBanner :level="overall" :ts="assessment?.ts" />
      <EarthSummary v-if="overall === 3 && assessment?.earth_summary" :text="assessment.earth_summary" />
      <ReasonList :systems="assessment?.systems" :selected="selected" @clear="selected = null" />
      <RecommendationList :items="assessment?.recommendations ?? []" :color="levelInfo(overall).color" />
      <TrendPanel :trends="assessment?.trends ?? []" />
      <div class="row">
        <VitalsCard :telemetry="crew.telemetry" :exercise="crew.lastExercise" />
        <CabinCard :environment="assessment?.systems?.environment" :cabin="crew.telemetry?.cabin" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.status-grid {
  display: grid;
  grid-template-columns: minmax(240px, 340px) 1fr;
  gap: 1rem;
  align-items: start;
}
.col-body {
  position: sticky;
  top: calc(env(safe-area-inset-top, 0px) + 1rem);
}
.col-panels {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}
.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
}
.waiting {
  margin: 0;
  border-left: 4px solid var(--accent);
}
.hint {
  text-align: center;
  font-size: 0.85rem;
  margin: 0.5rem 0 0;
}
@media (max-width: 720px) {
  .status-grid {
    grid-template-columns: 1fr;
  }
  .col-body {
    position: static;
  }
}
</style>
