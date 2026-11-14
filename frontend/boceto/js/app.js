// Lógica de la consola. Habla con la API (api/main.py):
//   GET  /api/v1/crew/{id}/latest      → último estado y nombre, al cargar y al reconectar
//   GET  /api/v1/crew/{id}/telemetry   → histórico, para las líneas de pulso y temperatura
//   GET  /api/v1/events                → registro de eventos guardados
//   WS   /ws                           → mensajes { type, data }: telemetry, event, assessment
//   POST /api/v1/checks                → chequeo diario (contrato ②)
// Todo lo que se pinta sale de esos mensajes: niveles, motivos, acciones y
// tendencias (con sus puntos y su recta) los calcula el motor (risk/).
// Se puede cambiar desde la URL: console.html?api=http://192.168.1.20:8000&crew=F3786E09

import { createPlanet } from "./planet.js";
import { createHologram } from "./hologram.js";
import { trendChart, attachTrendHover } from "./trendchart.js";
import { mergeReadings, sparkPath } from "./data.js";

// ─── Configuración ──────────────────────────────────────────────────────────
const params = new URLSearchParams(location.search);
// Por defecto, la API en el mismo ordenador que sirve la web, puerto 8000 (uvicorn)
const API_URL = (params.get("api") ?? (location.port === "5173" ? `${location.protocol}//${location.hostname}:8000` : location.origin)).replace(/\/$/, "");
const WS_PATH = "/ws";
const API_KEY = params.get("key"); // GET and manual checks do not require a key.
// Tarjetas del kit (api/crew.py). Los que lleguen por el WebSocket con otro
// crew_id se añaden solos.
const KNOWN_CREW = ["F3786E09", "336F8312"];
const STALE_S = 15;            // criterio propio: varios mensajes seguidos perdidos (la placa manda cada 2 s)
const HISTORY = 48;            // puntos de las líneas de pulso y temperatura

const LEVEL_NAME = { 0: "Nominal", 1: "Watch", 2: "Alert", 3: "Critical", null: "No data" };
const SYSTEMS = [
  ["cardiovascular", "Cardiovascular"],
  ["neuro", "Neuro"],
  ["musculoskeletal", "Musculoskeletal"],
  ["environment", "Environment"],
];
// Alertas locales de la placa (firmware/uno_sensores/config.h). No son niveles del motor.
const BOARD_ALERT = {
  HR_HIGH: "Pulse > 120", HR_LOW: "Pulse < 45", BODY_TEMP_HIGH: "Body temp > 38.0 °C", BODY_TEMP_LOW: "Body temp < 35.5 °C",
  CABIN_TEMP_HIGH: "Cabin > 28 °C", CABIN_TEMP_LOW: "Cabin < 18 °C", HEAT_INDEX_HIGH: "Heat index > 32 °C", CONDENSATION_HIGH: "Condensation risk high",
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const lv = (level) => (level == null ? "" : String(level));      // valor de data-level
const name = (level) => LEVEL_NAME[level ?? null];
const hms = (ts) => new Date(ts).toISOString().slice(11, 19);
const crewOf = (id) => state.crew.get(id) ?? { crew_id: id ?? "", name: id ?? "Select a crew member or scan a card", role: "" };
const crewList = () => [...state.crew.values()];
const tsMs = (ts) => { const t = Date.parse(ts ?? ""); return Number.isNaN(t) ? null : t; };
const ageS = (ms) => (ms == null ? null : Math.max(0, Math.round((Date.now() - ms) / 1000)));
const ago = (s) => (s == null ? "—" : s < 60 ? `${s} s ago` : `${Math.floor(s / 60)} min ago`);

// ─── Estado ─────────────────────────────────────────────────────────────────
const state = {
  crew: new Map(),             // crew_id -> { crew_id, name, role }
  crewId: params.get("crew") ?? KNOWN_CREW[0],
  followStation: !params.has("crew"),
  stationTs: 0,
  focus: null,                 // sistema filtrado, o null
  assessment: {},              // crew_id -> última evaluación ③
  telemetry: {},               // crew_id -> última telemetría ①
  hrHistory: {},               // crew_id -> últimos pulsos, para la gráfica
  tempHistory: {},             // crew_id -> últimas temperaturas corporales, para la gráfica
  samples: {},
  lastExercise: {},
  seenEvents: new Set(),
  lastPacket: {},              // crew_id -> hora local de llegada (ms)
  packets: 0,
  met: null,                   // { s, at }: último met_s recibido y cuándo
  log: [],
  logOnlySelected: false,
  acked: new Set(),            // avisos reconocidos en esta consola
  source: "connecting",        // connecting | live | lost (estado del WebSocket)
};
let lastRecs = null, lastEarth = null;       // para no repintar lo que no cambia

// ─── 3D ─────────────────────────────────────────────────────────────────────
createPlanet($("planet"), { horizon: 0.58, radius: (w) => w * 0.9, parallax: false });
const holo = createHologram($("body"), { onPick: setFocus });
attachTrendHover($("trends"));

function setFocus(system) {
  state.focus = state.focus === system ? null : system;
  holo.setFocus(state.focus);
  renderSystems();
}

// ─── Entrada de datos ───────────────────────────────────────────────────────
function addCrew(id, name, role) {
  const known = state.crew.get(id);
  if (known && !name) return;
  state.crew.set(id, { crew_id: id, name: name ?? known?.name ?? id, role: role ?? known?.role ?? "" });
  if (!state.followStation && state.crewId && !state.crew.has(state.crewId)) state.crewId = id;
  renderCrewOptions(); renderRoster();
  if (id === state.crewId) $("scanCrew").textContent = `${crewOf(id).name} · ${id}`;
}

// `fromHistory`: datos pedidos por HTTP (no en directo); la antigüedad sale de su ts.
function onMessage({ type, data }, { fromHistory = false } = {}) {
  if (!data) return;
  // Con varias placas a la vez, la telemetría alterna de tripulante cada 2 s:
  // "Follow sensor" sigue los fichajes RFID, y la telemetría solo si no hay nadie seleccionado.
  if (!fromHistory && type === "telemetry" && !state.crewId) applyStation({ crew_id: data.crew_id, ts: data.ts });
  if (!fromHistory && type === "event" && data.type === "crew_checkin") {
    applyStation({ crew_id: data.data?.action === "in" ? data.crew_id : null, ts: data.ts });
  }
  if (!data || !data.crew_id) return;            // sin tripulante (nadie ha fichado con la tarjeta)
  const id = data.crew_id;
  if (!state.crew.has(id)) addCrew(id);
  if (type === "assessment") {
    const prev = state.assessment[id];
    if (prev && tsMs(prev.ts) && tsMs(data.ts) && tsMs(data.ts) < tsMs(prev.ts)) return;   // llegó tarde
    logChanges(state.assessment[id], data);
    state.assessment[id] = data;
    renderRoster(); renderAlert();
    if (id === state.crewId) renderAssessment();
  } else if (type === "telemetry") {
    const prev = state.telemetry[id];
    const samples = state.samples[id] = mergeReadings(state.samples[id] ?? [], [data], HISTORY);
    state.hrHistory[id] = samples.map((m) => m.vitals?.heart_rate_bpm ?? null);
    state.tempHistory[id] = samples.map((m) => m.vitals?.body_temp_c ?? null);
    if (prev && (tsMs(prev.ts) ?? 0) >= (tsMs(data.ts) ?? 0)) {
      if (id === state.crewId) renderVitals();
      return;
    }
    state.telemetry[id] = data;
    state.lastPacket[id] = Math.min(Date.now(), tsMs(data.ts) ?? 0) || null;
    state.packets++;
    if (typeof data.met_s === "number" && !fromHistory) state.met = { s: data.met_s, at: Date.now() };
    if (id === state.crewId) renderVitals();
    renderRoster();
  } else if (type === "event") {
    const key = `${data.device_id}|${data.ts}|${data.type}`;
    if (state.seenEvents.has(key)) return;
    state.seenEvents.add(key);
    const d = data.data ?? {};
    if (data.type === "exercise_summary") {
      state.lastExercise[id] = data;
      if (id === state.crewId) renderVitals();
    }
    const msg = {
      exercise_summary: `Exercise: ${d.reps ?? "?"} ${d.exercise ?? ""} reps in ${d.duration_s ?? "?"} s`,
      inactivity: `No movement for ${d.still_for_s ?? "?"} s`,
      crew_checkin: d.action === "out" ? "Crew member checked out" : "Crew member checked in",
    }[data.type] ?? `Event: ${data.type}`;
    addLog(data, data.severity === "medium" ? 1 : undefined, msg);     // info = sin nivel
  } else if (type === "check") {
    addLog(data, undefined, "Daily check received");
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
        <span class="chip">${e.level === undefined ? "Info" : name(e.level)}</span><span class="msg">${esc(e.msg)}</span></li>`).join("")
    : `<li><span class="msg dim">No events yet.</span></li>`;
}
$("logFilter").addEventListener("click", (e) => {
  state.logOnlySelected = !state.logOnlySelected;
  e.currentTarget.setAttribute("aria-pressed", String(state.logOnlySelected));
  renderLog();
});

// ─── Tripulación ────────────────────────────────────────────────────────────
function renderRoster() {
  const crew = crewList();
  $("crewCount").textContent = `${crew.length} ON BOARD`;
  if (!crew.length) { $("roster").innerHTML = `<p class="pb empty">Waiting for crew data…</p>`; return; }
  $("roster").innerHTML = crew.map((c) => {
    const role = c.role ? `${esc(c.role)} · ` : "";
    const a = state.assessment[c.crew_id], t = state.telemetry[c.crew_id];
    const age = ageS(state.lastPacket[c.crew_id]);
    const hr = t?.vitals?.heart_rate_bpm;
    return `<button class="crew" data-crew="${esc(c.crew_id)}" data-level="${lv(a?.overall_level)}" aria-pressed="${c.crew_id === state.crewId}">
      <b>${esc(c.name)}</b><span class="chip">${name(a?.overall_level)}</span>
      <span class="sub">${role}${esc(c.crew_id)}${t?.device_id ? ` · ${esc(t.device_id)}` : ""}</span>
      <span class="meta mono ${age != null && age > STALE_S ? "stale" : ""}">${typeof hr === "number" ? `${hr} bpm · ` : ""}${ago(age)}</span>
    </button>`;
  }).join("");
}
$("roster").addEventListener("click", (e) => {
  const b = e.target.closest("[data-crew]");
  if (b) selectCrew(b.dataset.crew);
});
function selectCrew(id, { station = false } = {}) {
  if (!station) state.followStation = false;
  $("followStation").setAttribute("aria-pressed", String(state.followStation));
  if (id !== state.crewId) resetCheck();
  state.crewId = id;
  state.focus = null;
  holo.setFocus(null);
  lastRecs = null;
  lastEarth = undefined;
  $("checkCrew").value = id;
  renderRoster(); renderAssessment(); renderVitals(); renderLog(); renderPayload();
  if (id) loadCrew(id);
}

function applyStation(data) {
  if (!state.followStation || (tsMs(data.ts) ?? 0) < state.stationTs) return;
  state.stationTs = tsMs(data.ts) ?? state.stationTs;
  const id = data.crew_id ?? null;
  if (id && !state.crew.has(id)) addCrew(id);
  if (id !== state.crewId) selectCrew(id, { station: true });
}
$("followStation").addEventListener("click", async () => {
  state.followStation = true;
  $("followStation").setAttribute("aria-pressed", "true");
  const active = await getJSON("/api/v1/crew/active").catch(() => null);
  if (active) applyStation(active);
});

// ─── Aviso: nivel 2 o 3 que nadie ha reconocido ─────────────────────────────
function currentAlert() {
  let worst = null;
  for (const c of crewList()) {
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
    <span class="msg"><b>${esc(al.crew.name)}</b> <span class="mono dim">${esc(al.crew.crew_id)} · ${hms(al.ts)} UTC</span><br>${esc(al.label)}: ${esc(al.reason)}</span>
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
  if (!a) {
    // Sin evaluación todavía: todo en gris ("No data"), nunca en verde
    $("overall").dataset.level = ""; $("overall").textContent = name(null);
    $("overallTs").textContent = "WAITING FOR ASSESSMENT";
    holo.setLevels(Object.fromEntries(SYSTEMS.map(([k]) => [k, null])));
    renderSystems();
    $("trends").innerHTML = `<p class="empty">No assessment received yet.</p>`;
    $("recs").innerHTML = `<li class="empty" style="display:block">No assessment received yet.</li>`;
    $("downlink").hidden = true;
    lastRecs = lastEarth = null;
    return;
  }

  $("overall").dataset.level = lv(a.overall_level);
  $("overall").textContent = name(a.overall_level);
  $("overallTs").textContent = `ASSESSED ${hms(a.ts)} UTC`;

  holo.setLevels(Object.fromEntries(SYSTEMS.map(([k]) => [k, a.systems?.[k]?.level ?? null])));
  renderSystems();

  // Una gráfica por indicador con al menos 7 medidas. Primero las que cruzan un
  // umbral; luego los chequeos y las series, y después los sensores.
  const trends = [...(a.trends ?? [])].sort((x, y) =>
    (x.crosses_in == null) - (y.crosses_in == null) || (x.basis === "time") - (y.basis === "time"));
  $("trends").innerHTML = trends.length
    ? trends.map((t) => trendChart(t, { levelName: name })).join("")
    : `<p class="empty">A trend line appears after 7 readings of the same measure: 7 daily checks, 7 push-up sets or 14 s of sensor data.</p>`;
  $("trendCount").textContent = trends.length ? `${trends.filter((t) => t.crosses_in != null).length} OF ${trends.length} CROSSING` : "";

  const recs = JSON.stringify(a.recommendations ?? []);
  if (recs !== lastRecs) {
    lastRecs = recs;
    $("recs").innerHTML = a.recommendations?.length
      ? a.recommendations.map((r, i) => `<li style="animation-delay:${i * 0.06}s"><span>${esc(r)}</span></li>`).join("")
      : `<li class="empty" style="display:block">${a.overall_level == null ? "Complete your daily check or connect the sensors to receive guidance." : "No action required."}</li>`;
  }

  // Full text immediately: a live update must not restart an unfinished animation.
  const earth = a.earth_summary ?? null;
  $("downlink").hidden = !earth;
  if (!earth) $("earth").textContent = "";
  if (earth !== lastEarth) {
    lastEarth = earth;
    $("downlink").hidden = !earth;
    if (earth) $("earth").textContent = earth;
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
  const validHr = hist.filter((v) => typeof v === "number");
  const lo = Math.min(...validHr, 50), hi = Math.max(...validHr, 110);
  const line = sparkPath(hist, lo, hi);
  const temps = state.tempHistory[state.crewId] ?? [];
  const validTemp = temps.filter((v) => typeof v === "number");
  const tLo = Math.min(...validTemp, 36), tHi = Math.max(...validTemp, 37.5);
  const tempLine = sparkPath(temps, tLo, tHi);
  const motion = t?.motion?.activity === "still" ? `Still ${num(t.motion.still_for_s)} s` : (t?.motion?.activity ?? "—");
  const ex = state.lastExercise[state.crewId]?.data;
  const exercise = ex ? `${num(ex.reps)} reps · ${num(ex.duration_s)} s` : "—";
  const risk = t?.cabin?.condensation_risk;
  const alerts = (t?.alerts ?? []).map((code) => `<span class="chip" data-level="1">${esc(BOARD_ALERT[code] ?? code)}</span>`).join("");

  holo.setBpm(t?.vitals?.heart_rate_bpm);
  $("vitals").innerHTML = `
    <div class="vital wide"><p class="label">Heart rate</p>
      <p class="val">${num(t?.vitals?.heart_rate_bpm)}<small>bpm</small></p>
      <svg viewBox="0 0 100 44" preserveAspectRatio="none"><path d="${line}" fill="none" stroke="currentColor" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="vital wide"><p class="label">Body temp</p>
      <p class="val">${num(t?.vitals?.body_temp_c, 1)}<small>°C</small></p>
      <svg viewBox="0 0 100 44" preserveAspectRatio="none"><path d="${tempLine}" fill="none" stroke="currentColor" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="vital wide"><p class="label">Motion</p><p class="val txt">${esc(motion)}</p></div>
    <div class="vital wide"><p class="label">Last push-up set</p><p class="val txt">${esc(exercise)}</p></div>
    <div class="vital"><p class="label">Cabin temp</p><p class="val">${num(t?.cabin?.temp_c, 1)}<small>°C</small></p></div>
    <div class="vital"><p class="label">Humidity</p><p class="val">${num(t?.cabin?.humidity_pct)}<small>%</small></p></div>
    <div class="vital"><p class="label">Heat index</p><p class="val">${num(t?.cabin?.heat_index_c, 1)}<small>°C</small></p></div>
    <div class="vital"><p class="label">Dew point</p><p class="val">${num(t?.cabin?.dew_point_c, 1)}<small>°C</small></p></div>
    <div class="vital wide"><p class="label">Condensation risk</p><p class="val txt">${esc(risk ?? "—")}</p></div>
    <div class="vital wide"><p class="label">Board alerts</p><p class="alerts">${alerts || `<span class="dim">${t ? "None" : "—"}</span>`}</p></div>`;
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
// Pastilla de arriba: conexión con la base y si llegan datos del sensor.
function renderSource() {
  const age = ageS(state.lastPacket[state.crewId]);
  const ok = state.source === "live" && age != null && age <= STALE_S;
  const pill = $("linkPill");
  pill.classList.toggle("live", ok);
  pill.classList.toggle("lost", state.source !== "connecting" && !ok);
  $("linkText").textContent =
    state.source === "connecting" ? "CONNECTING…" :
    state.source === "lost" ? "NO LINK TO BASE" :
    ok ? "SENSOR OK" : "NO SENSOR DATA";
}
function renderLink() {
  const t = state.telemetry[state.crewId];
  const age = ageS(state.lastPacket[state.crewId]);
  const stale = age == null || age > STALE_S;
  const quality = t?.vitals?.hr_quality;
  $("linkState").textContent = stale ? "NO SIGNAL" : "CONNECTED";
  $("linkState").style.color = stale ? "var(--lv1)" : "var(--lv0)";
  $("link").innerHTML = `
    <dt>Device</dt><dd>${esc(t?.device_id ?? "—")}</dd>
    <dt>Last reading</dt><dd class="${stale ? "warn" : ""}">${ago(age)}</dd>
    <dt>Pulse signal quality</dt><dd>${typeof quality === "number" ? `${Math.round(quality * 100)} %` : "—"}</dd>
    <dt>Status</dt><dd class="${stale ? "warn" : ""}">${stale ? "Check that the device is on and in place" : "Reading normally"}</dd>`;
}
function renderClock() {
  $("utc").textContent = new Date().toISOString().slice(11, 19);
  $("device").textContent = state.telemetry[state.crewId]?.device_id ?? "—";
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
let checkStep = 0;
function showCheckStep(step) {
  checkStep = Math.max(0, Math.min(2, step));
  for (const panel of document.querySelectorAll("[data-check-step]")) panel.hidden = +panel.dataset.checkStep !== checkStep;
  $("checkStep").textContent = `STEP ${checkStep + 1} OF 3 · ${["MOOD", "BLOOD PRESSURE", "GLUCOSE"][checkStep]}`;
  $("checkBack").hidden = checkStep === 0;
  $("checkNext").hidden = checkStep === 2;
  $("checkSubmit").hidden = checkStep !== 2;
}
function resetCheck() {
  mood = null;
  for (const id of ["sys", "dia", "glu"]) $(id).value = "";
  for (const button of $("mood").children) button.setAttribute("aria-checked", "false");
  $("checkMsg").textContent = "Leave a field empty if you did not measure it today.";
  showCheckStep(0);
}
function validatePressure() {
  const sys = field("sys"), dia = field("dia");
  if ((sys == null) !== (dia == null)) return "Enter both blood pressure values, or leave both blank.";
  if (sys != null && (!Number.isInteger(sys) || !Number.isInteger(dia) || sys < 60 || sys > 260 || dia < 30 || dia > 160 || dia >= sys))
    return "Please check your blood pressure values. Systolic must be higher than diastolic.";
  return null;
}
function validateCheck() {
  if (!state.crewId) return "Select a crew member or scan a card first.";
  const bpError = validatePressure();
  if (bpError) { showCheckStep(1); return bpError; }
  const glucose = field("glu");
  if (glucose != null && (glucose < 20 || glucose > 600)) return "Please check your glucose value (20–600 mg/dL).";
  if (mood == null && field("sys") == null && glucose == null) return "Answer at least one question before sending your check.";
  return null;
}
$("checkBack").addEventListener("click", () => showCheckStep(checkStep - 1));
$("checkNext").addEventListener("click", () => {
  const error = checkStep === 1 ? validatePressure() : null;
  if (error) { $("checkMsg").textContent = error; return; }
  $("checkMsg").textContent = "Leave a field empty if you did not measure it today.";
  showCheckStep(checkStep + 1);
});
function renderCrewOptions() {
  $("checkCrew").innerHTML = `<option value="">Select crew member</option>` + crewList().map((c) => `<option value="${esc(c.crew_id)}">${esc(c.name)} · ${esc(c.crew_id)}</option>`).join("");
  $("checkCrew").value = state.crewId;
}
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
    ts: new Date().toISOString(),
    blood_pressure: field("sys") == null && field("dia") == null ? null : { systolic: field("sys"), diastolic: field("dia") },
    glucose_mg_dl: field("glu"),
    mood,
  };
}
// Lo que se envía sigue el contrato ② (contracts/check.example.json); no se enseña en pantalla.
function renderPayload() {}
$("checkForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (checkStep < 2) { $("checkNext").click(); return; }
  const error = validateCheck();
  if (error) { $("checkMsg").textContent = error; return; }
  const check = buildCheck();
  const btn = e.currentTarget.querySelector("[type=submit]");
  btn.disabled = true;
  $("checkMsg").textContent = "Sending…";
  try {
    const r = await fetch(API_URL + "/api/v1/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(check),
    });
    // 409 = ya estaba guardado (mismo crew_id y ts)
    $("checkMsg").textContent = r.ok || r.status === 409 ? "Check saved. Thank you."
      : r.status === 422 ? "Some values are not valid. Check them and try again."
      : "Could not save the check. Try again in a minute.";
    if (r.ok || r.status === 409) {
      addLog(check, undefined, "Daily check received");
      await loadCrew(check.crew_id);
      if (state.crewId === check.crew_id) { resetCheck(); showView("monitor"); }
    }
  } catch {
    $("checkMsg").textContent = "No link to base. Try again in a minute.";
  } finally { btn.disabled = false; }
});

// ─── Conexión con la API ────────────────────────────────────────────────────
const headers = () => API_KEY ? { "X-API-Key": API_KEY } : {};

async function getJSON(path) {
  const r = await fetch(API_URL + path, { headers: headers() });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET ${path}: HTTP ${r.status}`);
  return r.json();
}

// Último estado de un tripulante, y su histórico de telemetría para las líneas.
async function loadCrew(id) {
  const from = encodeURIComponent(new Date(Date.now() - 7 * 86400000).toISOString());
  const [latest, history, events] = await Promise.all([
    getJSON(`/api/v1/crew/${encodeURIComponent(id)}/latest`).catch((e) => { console.warn(e); return null; }),
    getJSON(`/api/v1/crew/${encodeURIComponent(id)}/telemetry?limit=${HISTORY}`).catch(() => null),
    getJSON(`/api/v1/events?crew_id=${encodeURIComponent(id)}&from=${from}`).catch(() => null),
  ]);
  if (latest) addCrew(id, latest.crew_name, latest.crew_role);
  if (events) for (const event of events) onMessage({ type: "event", data: event }, { fromHistory: true });
  if (latest?.last_exercise) state.lastExercise[id] = latest.last_exercise;
  if (Array.isArray(history)) {
    for (const t of history.slice(-HISTORY)) onMessage({ type: "telemetry", data: { ...t, crew_id: t.crew_id ?? id } }, { fromHistory: true });
  }
  if (latest?.telemetry) onMessage({ type: "telemetry", data: latest.telemetry }, { fromHistory: true });
  if (latest?.assessment) onMessage({ type: "assessment", data: latest.assessment });
  else if (latest?.assessment_error) {
    delete state.assessment[id];
    if (id === state.crewId) renderAssessment();
  }
}
async function loadAll() {
  const crew = await getJSON("/api/v1/crew").catch(() => null);
  if (Array.isArray(crew)) for (const c of crew) addCrew(c.crew_id, c.name, c.role);
  const active = await getJSON("/api/v1/crew/active").catch(() => null);
  if (active) applyStation(active);
  await Promise.all([...new Set([...KNOWN_CREW, ...state.crew.keys()])].map(loadCrew));
}

// WebSocket con reconexión: espera 1, 2, 4… s, hasta 30 s. Al volver, se pide el estado.
let retry = 0;
function connect() {
  const ws = new WebSocket(API_URL.replace(/^http/, "ws") + WS_PATH);
  ws.onopen = () => { retry = 0; state.source = "live"; renderSource(); loadAll(); };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg && typeof msg.type === "string") onMessage(msg);
  };
  ws.onclose = () => {
    state.source = "lost"; renderSource();
    setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
  };
}

// ─── Arranque ───────────────────────────────────────────────────────────────
for (const id of new Set([...KNOWN_CREW, state.crewId])) state.crew.set(id, { crew_id: id, name: id, role: "" });
renderCrewOptions();
renderSource(); renderClock(); renderRoster(); renderAssessment(); renderVitals();
renderLog(); renderLink(); renderPayload();
setInterval(() => { renderClock(); renderRoster(); renderLink(); renderAge(); renderSource(); }, 1000);
// Refresh assessments even if the station stops sending; old data must expire.
setInterval(() => { if (state.source === "live") loadAll(); }, 15000);
connect();
