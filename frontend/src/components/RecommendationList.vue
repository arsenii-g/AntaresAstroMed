<script setup>
// Recomendaciones del motor, en inglés. La primera es la acción del nivel.
defineProps({
  items: { type: Array, default: () => [] },
  color: { type: String, default: 'var(--accent)' },
})
</script>

<template>
  <section class="card">
    <header class="card-head"><h2>Recommendations</h2></header>
    <p v-if="!items.length" class="muted">No actions needed.</p>
    <ol v-else>
      <li v-for="(r, i) in items" :key="i" :class="{ first: i === 0 }" :style="i === 0 ? { borderColor: color } : null">
        {{ r }}
      </li>
    </ol>
  </section>
</template>

<style scoped>
ol {
  margin: 0;
  padding-left: 1.5rem;
}
li + li {
  margin-top: 0.3rem;
}
.first {
  font-weight: 700;
  border-left: 4px solid;
  padding-left: 0.5rem;
  margin-left: -0.25rem;
}
</style>
