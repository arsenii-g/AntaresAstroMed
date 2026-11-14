// Lógica de la consola. Habla con la API (api/main.py):
//   GET  /api/v1/crew/{id}/latest      → último estado y nombre/rol, al cargar y al reconectar
//   GET  /api/v1/crew/{id}/telemetry   → histórico, para las líneas de pulso y temperatura
//   WS   /ws                           → mensajes { type, data }: telemetry, event, check, assessment
//   POST /api/v1/checks                → chequeo diario (contrato ②)
// Se puede cambiar desde la URL: console.html?api=http://192.168.1.20:8000&crew=F3786E09

import { createPlanet } from "./planet.js";
import { createHologram } from "./hologram.js";
import { trendChart, attachTrendHover } from "./trendchart.js";

// ─── Configuración ──────────────────────────────────────────────────────────
const params = new URLSearchParams(location.search);
// Por defecto, la API en el mismo ordenador que sirve la web, puerto 8000 (uvicorn)
const API_URL = (params.get("api") ?? `${location.protocol}//${location.hostname || "localhost"}:8000`).replace(/\/$/, "");
const WS_PATH = "/ws";
const API_KEY = params.get("key") ?? "spacehealth-dev-key-2026";   // API_KEY_SECRET de api/main.py
// Tripulantes que la API conoce (crew_names en api/main.py). Los que lleguen por el
// WebSocket con otro crew_id se añaden solos.
const KNOWN_CREW = ["F3786E09", "04D4E5F6"];
const STALE_S = 15;            // criterio propio: varios mensajes seguidos perdidos (la placa manda cada 2 s)
const HISTORY = 48;            // puntos de las líneas de pulso y temperatura

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
const crewOf = (id) => state.crew.get(id) ?? { crew_id: id, name: id, role: "" };
const crewList = () => [...state.crew.values()];
const tsMs = (ts) => { const t = Date.parse(ts ?? ""); return Number.isNaN(t) ? null : t; };
const ageS = (ms) => (ms == null ? null : Math.max(0, Math.round((Date.now() - ms) / 1000)));
const ago = (s) => (s == null ? "—" : s < 60 ? `${s} s ago` : `${Math.floor(s / 60)} min ago`);

// ─── Estado ─────────────────────────────────────────────────────────────────
const state = {
  crew: new Map(),             // crew_id -> { crew_id, name, role }
  crewId: params.get("crew") ?? KNOWN_CREW[0],
  focus: null,                 // sistema filtrado, o null
  assessment: {},              // crew_id -> última evaluación ③
  telemetry: {},               // crew_id -> última telemetría ①
  hrHistory: {},               // crew_id -> últimos pulsos, para la gráfica
  tempHistory: {},             // crew_id -> últimas temperaturas corporales, para la gráfica
  lastPacket: {},              // crew_id -> hora local de llegada (ms)
  packets: 0,
  met: null,                   // { s, at }: último met_s recibido y cuándo
  log: [],
  logOnlySelected: false,
  acked: new Set(),            // avisos reconocidos en esta consola
  source: "connecting",        // connecting | live | lost (estado del WebSocket)
};
let lastRecs = null, lastEarth = null, typing = 0;       // para no repintar lo que no cambia

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
  if (!state.crew.has(state.crewId)) state.crewId = id;
  renderCrewOptions(); renderRoster();
  if (id === state.crewId) $("scanCrew").textContent = `${crewOf(id).name} · ${id}`;
}

// `fromHistory`: datos pedidos por HTTP (no en directo); la antigüedad sale de su ts.
function onMessage({ type, data }, { fromHistory = false } = {}) {
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
    if (fromHistory && prev && (tsMs(prev.ts) ?? 0) >= (tsMs(data.ts) ?? 0)) return;
    state.telemetry[id] = data;
    state.lastPacket[id] = fromHistory ? Math.min(Date.now(), tsMs(data.ts) ?? 0) || null : Date.now();
    state.packets++;
    const hr = data.vitals?.heart_rate_bpm;
    const hist = (state.hrHistory[id] ??= []);
    if (typeof hr === "number") { hist.push(hr); if (hist.length > HISTORY) hist.shift(); }
    const temp = data.vitals?.body_temp_c;
    const tempHist = (state.tempHistory[id] ??= []);
    if (typeof temp === "number") { tempHist.push(temp); if (tempHist.length > HISTORY) tempHist.shift(); }
    if (typeof data.met_s === "number" && !fromHistory) state.met = { s: data.met_s, at: Date.now() };
    if (id === state.crewId) renderVitals();
    renderRoster();
  } else if (type === "event") {
    const d = data.data ?? {};
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
    const a = state.assessment[c.crew_id], t = state.telemetry[c.crew_id];
    const age = ageS(state.lastPacket[c.crew_id]);
    const hr = t?.vitals?.heart_rate_bpm;
    return `<button class="crew" data-crew="${c.crew_id}" data-level="${lv(a?.overall_level)}" aria-pressed="${c.crew_id === state.crewId}">
      <b>${esc(c.name)}</b><span class="chip">${name(a?.overall_level)}</span>
      <span class="sub">${c.role ? `${esc(c.role)} · ` : ""}${c.crew_id}</span>
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

  $("trends").innerHTML = a.trends?.length
    // Una gráfica de 7 días por indicador; primero las que cruzan antes un umbral.
    ? [...a.trends]
        .sort((x, y) => (x.crosses_threshold_in_days ?? Infinity) - (y.crosses_threshold_in_days ?? Infinity))
        .map((t) => trendChart(t, { names: TREND_NAME, levelName: name }))
        .join("")
    : `<p class="empty">Not enough readings yet to draw a 7-day trend.</p>`;

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
  const temps = state.tempHistory[state.crewId] ?? [];
  const tLo = Math.min(...temps, 36), tHi = Math.max(...temps, 37.5);
  const tempLine = temps.map((v, i) => `${(i / 47) * 100},${40 - ((v - tLo) / (tHi - tLo || 1)) * 36}`).join(" ");
  const motion = t?.motion?.activity === "still" ? `Still ${num(t.motion.still_for_s)} s` : (t?.motion?.activity ?? "—");

  holo.setBpm(t?.vitals?.heart_rate_bpm);
  $("vitals").innerHTML = `
    <div class="vital wide"><p class="label">Heart rate</p>
      <p class="val">${num(t?.vitals?.heart_rate_bpm)}<small>bpm</small></p>
      <svg viewBox="0 0 100 44" preserveAspectRatio="none"><polyline points="${line}" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="vital wide"><p class="label">Body temp</p>
      <p class="val">${num(t?.vitals?.body_temp_c, 1)}<small>°C</small></p>
      <svg viewBox="0 0 100 44" preserveAspectRatio="none"><polyline points="${tempLine}" vector-effect="non-scaling-stroke"/></svg></div>
    <div class="vital wide"><p class="label">Motion</p><p class="val txt">${esc(motion)}</p></div>
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
function renderCrewOptions() {
  $("checkCrew").innerHTML = crewList().map((c) => `<option value="${c.crew_id}">${esc(c.name)} · ${c.crew_id}</option>`).join("");
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
  const btn = e.currentTarget.querySelector("[type=submit]");
  btn.disabled = true;
  $("checkMsg").textContent = "Sending…";
  try {
    const r = await fetch(API_URL + "/api/v1/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify(buildCheck()),
    });
    // 409 = ya estaba guardado (mismo crew_id y ts)
    $("checkMsg").textContent = r.ok || r.status === 409 ? "Check saved. Thank you."
      : r.status === 422 ? "Some values are not valid. Check them and try again."
      : "Could not save the check. Try again in a minute.";
  } catch {
    $("checkMsg").textContent = "No link to base. Try again in a minute.";
  } finally { btn.disabled = false; }
});

// ─── Conexión con la API ────────────────────────────────────────────────────
const headers = () => ({ "X-API-Key": API_KEY });

async function getJSON(path) {
  const r = await fetch(API_URL + path, { headers: headers() });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET ${path}: HTTP ${r.status}`);
  return r.json();
}

// Último estado de un tripulante, y su histórico de telemetría para las líneas.
async function loadCrew(id) {
  const [latest, history] = await Promise.all([
    getJSON(`/api/v1/crew/${encodeURIComponent(id)}/latest`).catch((e) => { console.warn(e); return null; }),
    state.hrHistory[id]?.length ? null
      : getJSON(`/api/v1/crew/${encodeURIComponent(id)}/telemetry`).catch((e) => { console.warn(e); return null; }),
  ]);
  if (latest) addCrew(id, latest.crew_name, latest.crew_role);
  if (Array.isArray(history)) {
    for (const t of history.slice(-HISTORY)) onMessage({ type: "telemetry", data: { ...t, crew_id: t.crew_id ?? id } }, { fromHistory: true });
  }
  if (latest?.telemetry) onMessage({ type: "telemetry", data: latest.telemetry }, { fromHistory: true });
  if (latest?.assessment) onMessage({ type: "assessment", data: latest.assessment });
}
const loadAll = () => Promise.all([...new Set([...KNOWN_CREW, ...state.crew.keys()])].map(loadCrew));

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
connect();
