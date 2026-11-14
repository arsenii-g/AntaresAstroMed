// Lógica de la consola. Recibe mensajes { type, data } (contrato ④) y pinta.
// Con API_URL = null usa los datos de ejemplo de mock.js.

import { createPlanet } from "./planet.js";
import { createHologram } from "./hologram.js";
import { CREW, subscribe as subscribeMock } from "./mock.js";

// ─── Configuración ──────────────────────────────────────────────────────────
const API_URL = null;          // p. ej. "http://localhost:8000" para usar la API real
const WS_PATH = "/ws";         // POR ACORDAR con Jesus: ruta del WebSocket
const API_KEY = "demo";        // cabecera X-API-Key, igual que la placa y el simulador
const STALE_S = 15;            // criterio propio: 3 mensajes seguidos perdidos (la placa manda cada 5 s)

const LEVEL_NAME = { 0: "Nominal", 1: "Watch", 2: "Alert", 3: "Critical", null: "No data" };
const SYSTEMS = [
  ["cardiovascular", "Cardiovascular"],
  ["neuro", "Neuro"],
  ["musculoskeletal", "Musculoskeletal"],
  ["environment", "Environment"],
];
const TREND_NAME = { pushup_reps: "Push-ups", glucose_mg_dl: "Glucose", systolic_mmhg: "Systolic pressure", diastolic_mmhg: "Diastolic pressure", mood: "Mood" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const lv = (level) => (level == null ? "" : String(level));      // valor de data-level
const name = (level) => LEVEL_NAME[level ?? null];
const hms = (ts) => new Date(ts).toISOString().slice(11, 19);
const crewOf = (id) => CREW.find((c) => c.crew_id === id) ?? { crew_id: id, name: id, role: "" };
const ageS = (ms) => (ms == null ? null : Math.max(0, Math.round((Date.now() - ms) / 1000)));
const ago = (s) => (s == null ? "—" : s < 60 ? `${s} s ago` : `${Math.floor(s / 60)} min ago`);

// ─── Estado ─────────────────────────────────────────────────────────────────
const state = {
  crewId: CREW[0].crew_id,
  focus: null,                 // sistema filtrado, o null
  assessment: {},              // crew_id -> última evaluación ③
  telemetry: {},               // crew_id -> última telemetría ①
  hrHistory: {},               // crew_id -> últimos pulsos, para la gráfica
  lastPacket: {},              // crew_id -> hora local de llegada (ms)
  packets: 0,
  met: null,                   // { s, at }: último met_s recibido y cuándo
  log: [],
  logOnlySelected: false,
  acked: new Set(),            // avisos reconocidos en esta consola
  source: API_URL ? "connecting" : "mock",
};
let lastRecs = null, lastEarth = null, typing = 0;       // para no repintar lo que no cambia

// ─── 3D ─────────────────────────────────────────────────────────────────────
createPlanet($("planet"), { horizon: 0.58, radius: (w) => w * 0.9, parallax: false });
const holo = createHologram($("body"), { onPick: setFocus });

function setFocus(system) {
  state.focus = state.focus === system ? null : system;
  holo.setFocus(state.focus);
  renderSystems();
}

// ─── Entrada de datos ───────────────────────────────────────────────────────
function onMessage({ type, data }) {
  if (!data || !data.crew_id) return;
  const id = data.crew_id;
  if (type === "assessment") {
    logChanges(state.assessment[id], data);
    state.assessment[id] = data;
    renderRoster(); renderAlert();
    if (id === state.crewId) renderAssessment();
  } else if (type === "telemetry") {
    state.telemetry[id] = data;
    state.lastPacket[id] = Date.now();
    state.packets++;
    const hr = data.vitals?.heart_rate_bpm;
    const hist = (state.hrHistory[id] ??= []);
    if (typeof hr === "number") { hist.push(hr); if (hist.length > 48) hist.shift(); }
    if (typeof data.met_s === "number") state.met = { s: data.met_s, at: Date.now() };
    if (id === state.crewId) renderVitals();
  }
}

// ─── Registro de eventos ────────────────────────────────────────────────────
function logChanges(prev, next) {
  if (!prev) {
    addLog(next, next.overall_level, `First assessment received · overall ${name(next.overall_level)}`);
    return;
  }
  for (const [key, label] of SYSTEMS) {
    const a = prev.systems?.[key]?.level ?? null, b = next.systems?.[key]?.level ?? null;
    if (a === b) continue;
    const why = next.systems?.[key]?.reasons?.[0];
    addLog(next, b, `${label} ${name(a)} → ${name(b)}${why ? ` · ${why}` : ""}`);
  }
}
function addLog(a, level, msg) {
  state.log.unshift({ ts: a.ts ?? new Date().toISOString(), crew_id: a.crew_id, level, msg });
  state.log.length = Math.min(state.log.length, 100);
  renderLog(true);
}
function renderLog(fresh = false) {
  const rows = state.log.filter((e) => !state.logOnlySelected || e.crew_id === state.crewId);
  $("log").innerHTML = rows.length
    ? rows.map((e, i) => `<li data-level="${lv(e.level)}" class="${fresh && i === 0 ? "new" : ""}">
        <time>${hms(e.ts)}</time><span class="who">${esc(crewOf(e.crew_id).name)}</span>
        <span class="chip">${name(e.level)}</span><span class="msg">${esc(e.msg)}</span></li>`).join("")
    : `<li><span class="msg dim">No events yet.</span></li>`;
}
$("logFilter").addEventListener("click", (e) => {
  state.logOnlySelected = !state.logOnlySelected;
  e.currentTarget.setAttribute("aria-pressed", String(state.logOnlySelected));
  renderLog();
});

// ─── Tripulación ────────────────────────────────────────────────────────────
function renderRoster() {
  $("crewCount").textContent = `${CREW.length} ON BOARD`;
  $("roster").innerHTML = CREW.map((c) => {
    const a = state.assessment[c.crew_id], t = state.telemetry[c.crew_id];
    const age = ageS(state.lastPacket[c.crew_id]);
    const hr = t?.vitals?.heart_rate_bpm;
    return `<button class="crew" data-crew="${c.crew_id}" data-level="${lv(a?.overall_level)}" aria-pressed="${c.crew_id === state.crewId}">
      <b>${esc(c.name)}</b><span class="chip">${name(a?.overall_level)}</span>
      <span class="sub">${esc(c.role)} · ${c.crew_id}</span>
      <span class="meta mono ${age != null && age > STALE_S ? "stale" : ""}">${typeof hr === "number" ? `${hr} bpm · ` : ""}${ago(age)}</span>
    </button>`;
  }).join("");
}
$("roster").addEventListener("click", (e) => {
  const b = e.target.closest("[data-crew]");
  if (b) selectCrew(b.dataset.crew);
});
function selectCrew(id) {
  state.crewId = id;
  lastRecs = lastEarth = null;
  $("checkCrew").value = id;
  renderRoster(); renderAssessment(); renderVitals(); renderLog(); renderPayload();
}

// ─── Aviso: nivel 2 o 3 que nadie ha reconocido ─────────────────────────────
function currentAlert() {
  let worst = null;
  for (const c of CREW) {
    const a = state.assessment[c.crew_id];
    if (!a || (a.overall_level ?? 0) < 2) continue;
    const [key, label] = SYSTEMS.find(([k]) => a.systems?.[k]?.level === a.overall_level) ?? SYSTEMS[0];
    const reason = a.systems?.[key]?.reasons?.[0] ?? "";
    const ack = `${c.crew_id}|${a.overall_level}|${reason}`;
    if (state.acked.has(ack)) continue;
    if (!worst || a.overall_level > worst.level) worst = { crew: c, level: a.overall_level, label, reason, ack, ts: a.ts };
  }
  return worst;
}
function renderAlert() {
  const al = currentAlert(), box = $("alert");
  box.hidden = !al;
  if (!al) return;
  box.dataset.level = lv(al.level);
  box.dataset.ack = al.ack;
  box.dataset.crew = al.crew.crew_id;
  box.innerHTML = `<span class="lvl"><i class="blink"></i>${name(al.level)}</span>
    <span class="msg"><b>${esc(al.crew.name)}</b> <span class="mono dim">${al.crew.crew_id} · ${hms(al.ts)} UTC</span><br>${esc(al.label)}: ${esc(al.reason)}</span>
    <span class="actions"><button class="btn small" data-act="view">View</button><button class="btn small" data-act="ack">Acknowledge</button></span>`;
}
$("alert").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act, box = $("alert");
  if (act === "view") { showView("monitor"); selectCrew(box.dataset.crew); }
  if (act === "ack") {
    state.acked.add(box.dataset.ack);
    addLog({ crew_id: box.dataset.crew, ts: new Date().toISOString() }, +box.dataset.level, "Alert acknowledged at this console");
    renderAlert();
  }
});

// ─── Evaluación del tripulante seleccionado ─────────────────────────────────
function renderAssessment() {
  const a = state.assessment[state.crewId];
  const c = crewOf(state.crewId);
  $("scanCrew").textContent = `${c.name} · ${c.crew_id}`;
  if (!a) return;

  $("overall").dataset.level = lv(a.overall_level);
  $("overall").textContent = name(a.overall_level);
  $("overallTs").textContent = `ASSESSED ${hms(a.ts)} UTC`;

  holo.setLevels(Object.fromEntries(SYSTEMS.map(([k]) => [k, a.systems?.[k]?.level ?? null])));
  renderSystems();

  $("trends").innerHTML = a.trends?.length
    ? a.trends.map((t) => {
        const days = t.crosses_threshold_in_days;
        const pct = days == null ? 15 : Math.max(8, 100 - (days / 7) * 100);
        return `<div class="trend"><b>${esc(TREND_NAME[t.indicator] ?? t.indicator)}</b>
          ${t.slope_per_day > 0 ? "+" : ""}${t.slope_per_day}/day · ${t.projected_7d} projected in 7 d
          ${days == null ? "" : `· crosses ${t.threshold} in <b>${days} d</b>`}
          <div class="bar"><i style="width:${pct}%"></i></div></div>`;
      }).join("")
    : `<p class="empty">No indicator is drifting toward a threshold.</p>`;

  const recs = JSON.stringify(a.recommendations ?? []);
  if (recs !== lastRecs) {
    lastRecs = recs;
    $("recs").innerHTML = a.recommendations?.length
      ? a.recommendations.map((r, i) => `<li style="animation-delay:${i * 0.06}s"><span>${esc(r)}</span></li>`).join("")
      : `<li class="empty" style="display:block">No action required.</li>`;
  }

  // Resumen para Tierra: solo en nivel 3; se escribe letra a letra
  const earth = a.earth_summary ?? null;
  if (earth !== lastEarth) {
    lastEarth = earth;
    $("downlink").hidden = !earth;
    const run = ++typing;
    if (earth) {
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      let i = still ? earth.length : 0;
      const step = () => {
        if (run !== typing) return;
        $("earth").textContent = earth.slice(0, i) + (i < earth.length ? "▌" : "");
        if (i++ < earth.length) setTimeout(step, 10);
      };
      step();
    }
  }
}
$("copyEarth").addEventListener("click", async (e) => {
  try { await navigator.clipboard.writeText(lastEarth ?? ""); e.target.textContent = "Copied"; }
  catch { e.target.textContent = "Copy failed"; }
  setTimeout(() => { e.target.textContent = "Copy"; }, 1500);
});

function renderSystems() {
  const a = state.assessment[state.crewId];
  $("systems").classList.toggle("has-focus", !!state.focus);
  $("sysFocus").textContent = state.focus ? state.focus.toUpperCase() : "ALL";
  $("systems").innerHTML = SYSTEMS.map(([key, label]) => {
    const s = a?.systems?.[key] ?? { level: null, reasons: [] };
    const reasons = s.reasons?.length
      ? s.reasons.map((r) => `<li>${esc(r)}</li>`).join("")
      : `<li class="none">${s.level == null ? "No data yet" : "Within range"}</li>`;
    return `<button class="sys ${state.focus === key ? "focus" : ""}" data-sys="${key}" data-level="${lv(s.level)}" aria-pressed="${state.focus === key}">
      <div class="sys-top"><span class="sys-name">${label}</span><span class="chip">${name(s.level)}</span></div>
      <ul>${reasons}</ul></button>`;
  }).join("");
}
$("systems").addEventListener("click", (e) => {
  const b = e.target.closest("[data-sys]");
  if (b) setFocus(b.dataset.sys);
});

function renderVitals() {
  const t = state.telemetry[state.crewId];
  const num = (v, digits = 0) => (typeof v === "number" ? v.toFixed(digits) : "—");   // null = sin dato
  const hist = state.hrHistory[state.crewId] ?? [];
  const lo = Math.min(...hist, 50), hi = Math.max(...hist, 110);
  const line = hist.map((v, i) => `${(i / 47) * 100},${40 - ((v - lo) / (hi - lo || 1)) * 36}`).join(" ");
  const motion = t?.motion?.activity === "still" ? `Still ${num(t.motion.still_for_s)} s` : (t?.motion?.activity ?? "—");

  holo.setBpm(t?.vitals?.heart_rate_bpm);
  $("vitals").innerHTML = `
    <div class="vital wide"><p class="label">Heart rate</p>
      <p class="val">${num(t?.vitals?.heart_rate_bpm)}<small>bpm</small></p>
      <svg viewBox="0 0 100 44" preserveAspectRatio="none"><polyline points="${line}" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="vital"><p class="label">Body temp</p><p class="val">${num(t?.vitals?.body_temp_c, 1)}<small>°C</small></p></div>
    <div class="vital"><p class="label">Motion</p><p class="val txt">${esc(motion)}</p></div>
    <div class="vital"><p class="label">Cabin temp</p><p class="val">${num(t?.cabin?.temp_c, 1)}<small>°C</small></p></div>
    <div class="vital"><p class="label">Humidity</p><p class="val">${num(t?.cabin?.humidity_pct)}<small>%</small></p></div>`;
  renderAge();
}

// ─── Enlace, reloj y antigüedad de los datos (cada segundo) ─────────────────
function renderAge() {
  const age = ageS(state.lastPacket[state.crewId]);
  const stale = age != null && age > STALE_S;
  $("vitalsAge").textContent = age == null ? "WAITING FOR SENSOR" : stale ? `NO NEW DATA · ${ago(age).toUpperCase()}` : ago(age).toUpperCase();
  $("vitalsAge").style.color = stale ? "var(--lv1)" : "";
  $("vitals").classList.toggle("stale", stale);
}
// Pastilla de arriba: si llegan datos del sensor. Con datos de ejemplo dice DEMO,
// para que nadie confunda la demo con datos reales.
function renderSource() {
  const age = ageS(state.lastPacket[state.crewId]);
  const ok = state.source !== "lost" && age != null && age <= STALE_S;
  const pill = $("linkPill");
  pill.classList.toggle("live", ok);
  pill.classList.toggle("lost", !ok);
  $("linkText").textContent = (ok ? "SENSOR OK" : "NO SENSOR DATA") + (state.source === "mock" ? " · DEMO" : "");
}
function renderLink() {
  const t = state.telemetry[state.crewId];
  const age = ageS(state.lastPacket[state.crewId]);
  const stale = age == null || age > STALE_S;
  const quality = t?.vitals?.hr_quality;
  $("linkState").textContent = stale ? "NO SIGNAL" : "CONNECTED";
  $("linkState").style.color = stale ? "var(--lv1)" : "var(--lv0)";
  $("link").innerHTML = `
    <dt>Last reading</dt><dd class="${stale ? "warn" : ""}">${ago(age)}</dd>
    <dt>Pulse signal</dt><dd>${typeof quality === "number" ? (quality >= 0.7 ? "Good" : "Weak: check the sensor") : "—"}</dd>
    <dt>Status</dt><dd class="${stale ? "warn" : ""}">${stale ? "Check that the device is on and in place" : "Reading normally"}</dd>`;
}
function renderClock() {
  $("utc").textContent = new Date().toISOString().slice(11, 19);
  if (state.met) {
    const s = state.met.s + (Date.now() - state.met.at) / 1000;
    const p = (n, l = 2) => String(Math.floor(n)).padStart(l, "0");
    $("met").textContent = `${p(s / 86400, 3)}/${p((s % 86400) / 3600)}:${p((s % 3600) / 60)}:${p(s % 60)}`;
  }
}

// ─── Vistas ─────────────────────────────────────────────────────────────────
function showView(v) {
  for (const b of document.querySelectorAll(".views button")) b.setAttribute("aria-selected", String(b.dataset.view === v));
  $("view-monitor").hidden = v !== "monitor";
  $("view-check").hidden = v !== "check";
}
document.querySelector(".views").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (b) showView(b.dataset.view);
});

// ─── Chequeo diario (contrato ②) ────────────────────────────────────────────
let mood = null;
$("checkCrew").innerHTML = CREW.map((c) => `<option value="${c.crew_id}">${esc(c.name)} · ${c.crew_id}</option>`).join("");
$("checkCrew").addEventListener("change", (e) => selectCrew(e.target.value));
$("mood").innerHTML = [1, 2, 3, 4, 5].map((n) => `<button type="button" role="radio" aria-checked="false" data-mood="${n}">${n}</button>`).join("");
$("mood").addEventListener("click", (e) => {
  const b = e.target.closest("[data-mood]");
  if (!b) return;
  mood = mood === +b.dataset.mood ? null : +b.dataset.mood;
  for (const x of $("mood").children) x.setAttribute("aria-checked", String(+x.dataset.mood === mood));
  renderPayload();
});

const field = (id) => { const v = $(id).value.trim(); return v === "" || isNaN(+v) ? null : +v; };
function buildCheck() {
  return {
    crew_id: state.crewId,
    ts: new Date().toISOString().slice(0, 19) + "Z",
    blood_pressure: { systolic: field("sys"), diastolic: field("dia") },
    glucose_mg_dl: field("glu"),
    mood,
  };
}
// Lo que se envía sigue el contrato ② (contracts/check.example.json); no se enseña en pantalla.
function renderPayload() {}
$("checkForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!API_URL) { $("checkMsg").textContent = "Check saved. Thank you."; console.info("Demo: check not sent", buildCheck()); return; }
  try {
    const r = await fetch(API_URL + "/api/v1/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify(buildCheck()),
    });
    $("checkMsg").textContent = r.ok ? "Check saved. Thank you." : "Could not save the check. Try again in a minute.";
  } catch { $("checkMsg").textContent = "Could not save the check. Try again in a minute."; }
});

// ─── Arranque ───────────────────────────────────────────────────────────────
// Todo lo de arriba ya está definido: ahora sí se conectan los datos.
renderSource(); renderClock(); renderRoster(); renderAssessment(); renderVitals();
renderLog(); renderLink(); renderPayload();
setInterval(() => { renderClock(); renderRoster(); renderLink(); renderAge(); renderSource(); }, 1000);

if (API_URL) {
  // API real. TODO (Roberto + Jesus): confirmar la ruta, y pedir el último
  // estado con GET /api/v1/crew/{crew_id}/latest al cargar la página.
  const ws = new WebSocket(API_URL.replace(/^http/, "ws") + WS_PATH);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onopen = () => { state.source = "live"; renderSource(); };
  ws.onclose = () => { state.source = "lost"; renderSource(); };
} else {
  subscribeMock(onMessage);
}
