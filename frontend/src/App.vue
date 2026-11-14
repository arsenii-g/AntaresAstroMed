<script setup>
import { computed, onMounted, ref } from 'vue'
import { startLiveData, useCrewState } from '@/stores/crewState'
import { crewProfile } from '@/crew'
import { levelInfo } from '@/levels'
import StatusView from '@/views/StatusView.vue'
import CheckView from '@/views/CheckView.vue'

const crew = useCrewState()
const tab = ref('status')
const profile = computed(() => crewProfile(crew.crewId))
const overall = computed(() => levelInfo(crew.assessment?.overall_level ?? null))

const TABS = [
  { id: 'check', label: 'Daily check' },
  { id: 'status', label: 'Status' },
]

onMounted(startLiveData)
</script>

<template>
  <header class="app-header" :style="{ borderBottomColor: overall.color }">
    <div class="brand">SpaceHealth</div>
    <div class="crew">
      <template v-if="profile">
        <strong>{{ profile.name }}</strong>
        <span v-if="profile.role" class="muted"> · {{ profile.role }}</span>
        <span class="muted mono"> · {{ crew.crewId }}</span>
      </template>
      <span v-else class="muted">No crew member checked in</span>
    </div>
    <div class="conn" :class="crew.connection" :title="crew.loadError ?? ''">
      <span class="conn-dot" />{{ crew.connection }}
    </div>
  </header>

  <nav class="tabs" role="tablist">
    <button
      v-for="t in TABS"
      :key="t.id"
      role="tab"
      :aria-selected="tab === t.id"
      :class="{ active: tab === t.id }"
      @click="tab = t.id"
    >
      {{ t.label }}
    </button>
  </nav>

  <main class="app-main">
    <StatusView v-if="tab === 'status'" />
    <CheckView v-else @done="tab = 'status'" />
  </main>
</template>
