// El motor solo conoce el crew_id (UID de la tarjeta). Nombre y rol los pone la web.
// Tarjetas del kit: contracts/README.md.
const CREW = {
  F3786E09: { name: 'Crew member 1', role: null },
  '336F8312': { name: 'Crew member 2', role: null },
}

export function crewProfile(id) {
  if (!id) return null
  return CREW[id] ?? { name: id, role: null }
}
