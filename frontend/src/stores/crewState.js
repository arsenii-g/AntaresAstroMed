// Estado en vivo del tripulante fichado. Reparte cada mensaje ④ según su `type`
// y solo guarda los del crew_id que se está mostrando.
import { reactive, readonly } from 'vue'
import { initialCrewId } from '@/config'
import { isNewer } from '@/format'
import { fetchLatest } from '@/services/api'
import { connectSocket } from '@/services/socket'

const state = reactive({
  crewId: initialCrewId(),
  telemetry: null, // último ① telemetría
  assessment: null, // última ③ evaluación
  lastExercise: null, // último evento exercise_summary
  connection: 'connecting', // connecting | online | offline
  loadError: null,
})

export function useCrewState() {
  return readonly(state)
}

export function selectCrew(id) {
  if (id === state.crewId) return
  state.crewId = id ?? null
  state.telemetry = null
  state.assessment = null
  state.lastExercise = null
  if (id) loadLatest(id)
}

async function loadLatest(id) {
  try {
    const latest = await fetchLatest(id)
    state.loadError = null
    if (!latest || state.crewId !== id) return
    if (latest.telemetry && isNewer(latest.telemetry, state.telemetry)) state.telemetry = latest.telemetry
    if (latest.assessment && isNewer(latest.assessment, state.assessment)) state.assessment = latest.assessment
  } catch (e) {
    state.loadError = e.message
  }
}

function handleMessage({ type, data }) {
  if (!data) return

  // Un crew_checkin cambia de perfil. Al cambiar de tarjeta llegan "out" y luego "in".
  if (type === 'event' && data.type === 'crew_checkin') {
    if (data.data?.action === 'in') selectCrew(data.crew_id)
    else if (data.data?.action === 'out' && data.crew_id === state.crewId) selectCrew(null)
    return
  }

  if (!data.crew_id || data.crew_id !== state.crewId) return

  if (type === 'telemetry') {
    if (isNewer(data, state.telemetry)) state.telemetry = data
  } else if (type === 'assessment') {
    if (isNewer(data, state.assessment)) state.assessment = data
  } else if (type === 'event' && data.type === 'exercise_summary') {
    if (isNewer(data, state.lastExercise)) state.lastExercise = data
  }
}

function setConnection(status) {
  const reconnected = status === 'online' && state.connection !== 'online'
  state.connection = status
  // Lo que se emitió mientras estábamos desconectados se recupera con el GET.
  if (reconnected && state.crewId) loadLatest(state.crewId)
}

let started = false
export function startLiveData() {
  if (started) return
  started = true
  connectSocket(handleMessage, setConnection)
}
