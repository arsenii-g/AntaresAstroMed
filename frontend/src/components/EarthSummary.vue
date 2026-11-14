<script setup>
// Solo en nivel 3: el `earth_summary` del motor, en inglés y sin tocar.
// Aún no hay endpoint para enviarlo, así que de momento se copia al portapapeles.
import { ref } from 'vue'

const props = defineProps({ text: { type: String, required: true } })
const copied = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    copied.value = true
    setTimeout(() => (copied.value = false), 2500)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <section class="card earth" role="alert">
    <header class="card-head"><h2>Summary for Earth</h2></header>
    <p class="text">{{ text }}</p>
    <button class="btn danger" @click="copy">{{ copied ? 'Copied ✓' : 'Copy summary for Earth' }}</button>
  </section>
</template>

<style scoped>
.earth {
  border: 2px solid var(--lvl-red);
}
.text {
  white-space: pre-wrap;
  margin: 0 0 0.75rem;
}
</style>
