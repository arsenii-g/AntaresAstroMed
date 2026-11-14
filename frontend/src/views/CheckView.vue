<script setup>
// Pestaña "Form" del boceto: chequeo guiado → ② POST /api/v1/checks.
// Lo que no se mide se manda como null ("sin dato"), nunca como 0.
// Los límites de los campos solo evitan erratas; los niveles los pone el motor.
import { computed, reactive, ref } from 'vue'
import { useCrewState } from '@/stores/crewState'
import { postCheck } from '@/services/api'
import { nowIso } from '@/format'

const emit = defineEmits(['done'])
const crew = useCrewState()

const MOODS = [
  { value: 5, label: 'Very good' },
  { value: 4, label: 'Good' },
  { value: 3, label: 'Okay' },
  { value: 2, label: 'Bad' },
  { value: 1, label: 'Very bad' },
]

const form = reactive({ mood: null, systolic: '', diastolic: '', glucose: '' })
const sending = ref(false)
const result = ref(null) // { ok, message }

const num = (v) => (v === '' || v == null ? null : Number(v))

const errors = computed(() => {
  const e = {}
  const sys = num(form.systolic)
  const dia = num(form.diastolic)
  const glu = num(form.glucose)
  if ((sys == null) !== (dia == null)) e.bp = 'Enter both systolic and diastolic, or leave both empty.'
  else if (sys != null && (sys < 60 || sys > 260 || dia < 30 || dia > 160)) e.bp = 'That reading looks wrong. Please check it.'
  else if (sys != null && dia >= sys) e.bp = 'Diastolic must be lower than systolic.'
  if (glu != null && (glu < 20 || glu > 600)) e.glucose = 'That reading looks wrong. Please check it.'
  return e
})

const hasAnswer = computed(() => form.mood != null || num(form.systolic) != null || num(form.glucose) != null)
const canSend = computed(() => crew.crewId && hasAnswer.value && !Object.keys(errors.value).length && !sending.value)

async function submit() {
  if (!canSend.value) return
  const sys = num(form.systolic)
  const check = {
    crew_id: crew.crewId,
    ts: nowIso(),
    blood_pressure: sys == null ? null : { systolic: sys, diastolic: num(form.diastolic) },
    glucose_mg_dl: num(form.glucose),
    mood: form.mood,
  }
  sending.value = true
  result.value = null
  try {
    await postCheck(check)
    result.value = { ok: true, message: 'Check sent. The status will update in a moment.' }
    Object.assign(form, { mood: null, systolic: '', diastolic: '', glucose: '' })
    setTimeout(() => emit('done'), 1200)
  } catch (e) {
    result.value = { ok: false, message: `Could not send the check (${e.message}). Try again.` }
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <form class="card check" @submit.prevent="submit">
    <p v-if="!crew.crewId" class="notice">Scan your crew card before starting the check.</p>

    <fieldset class="question">
      <legend><span class="qn">Question 1</span>How do you feel right now?</legend>
      <div class="moods">
        <label v-for="m in MOODS" :key="m.value" class="mood" :class="{ on: form.mood === m.value }">
          <input v-model="form.mood" type="radio" name="mood" :value="m.value" />
          <span class="mood-value">{{ m.value }}</span>
          <span>{{ m.label }}</span>
        </label>
      </div>
      <button v-if="form.mood != null" type="button" class="link" @click="form.mood = null">Skip this question</button>
    </fieldset>

    <fieldset class="question">
      <legend><span class="qn">Question 2</span>Blood pressure <span class="muted">(optional)</span></legend>
      <div class="inline">
        <label>Systolic <input v-model="form.systolic" type="number" inputmode="numeric" min="60" max="260" placeholder="118" /> mmHg</label>
        <label>Diastolic <input v-model="form.diastolic" type="number" inputmode="numeric" min="30" max="160" placeholder="76" /> mmHg</label>
      </div>
      <p v-if="errors.bp" class="error">{{ errors.bp }}</p>
    </fieldset>

    <fieldset class="question">
      <legend><span class="qn">Question 3</span>Fasting glucose <span class="muted">(optional)</span></legend>
      <label>Glucose <input v-model="form.glucose" type="number" inputmode="numeric" min="20" max="600" placeholder="92" /> mg/dL</label>
      <p v-if="errors.glucose" class="error">{{ errors.glucose }}</p>
    </fieldset>

    <div class="actions">
      <button class="btn primary" type="submit" :disabled="!canSend">{{ sending ? 'Sending…' : 'Send check' }}</button>
      <p v-if="result" :class="result.ok ? 'ok' : 'error'" role="status">{{ result.message }}</p>
    </div>
  </form>
</template>

<style scoped>
.check {
  max-width: 720px;
  margin: 0 auto;
}
.question {
  border: 0;
  border-bottom: 1px solid var(--line);
  margin: 0;
  padding: 1rem 0;
}
legend {
  font-size: 1.1rem;
  font-weight: 700;
  padding: 0;
  margin-bottom: 0.75rem;
}
.qn {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.moods {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 0.5rem;
}
.mood {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  padding: 0.6rem;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}
.mood.on {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.mood input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.mood:has(input:focus-visible) {
  outline: 2px solid var(--accent);
}
.mood-value {
  font-size: 1.4rem;
  font-weight: 800;
}
.inline {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
input[type='number'] {
  width: 6rem;
  margin: 0 0.3rem;
}
.actions {
  padding-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
}
.actions p {
  margin: 0;
}
.notice {
  background: var(--accent-soft);
  padding: 0.6rem 0.8rem;
  border-radius: var(--radius);
  margin: 0;
}
.error {
  color: var(--lvl-red);
  margin: 0.4rem 0 0;
}
.ok {
  color: var(--lvl-green);
}
.link {
  margin-top: 0.5rem;
}
</style>
