// Gráfica de 7 días de un elemento de `trends` (contrato ③).
//
// El motor no manda los puntos medidos: manda la recta de mínimos cuadrados
// (risk/trends.py), con x = días respecto a hoy:
//   valor(x) = intercepto + slope_per_day · x
//   projected_7d = valor(7)  →  intercepto = projected_7d − 7 · slope_per_day
// Se pinta esa recta: de −7 a 0 días es el ajuste a los datos (línea continua)
// y de 0 a +7 la proyección (discontinua), con la línea del umbral que cruzaría
// y el punto de cruce. Al pasar el ratón se ve el valor de la recta en ese día.
//
// Si la recta no cruza ningún umbral en 7 días, el motor manda threshold = null.
// Aun así se pinta, más tenue, la recta del siguiente umbral en la dirección de
// la pendiente (los mismos cortes que risk/thresholds.json), para ver a qué
// distancia queda. Las flexiones no la llevan: su umbral depende de la basal.

const DAYS = 7;
const W = 320, H = 150;
const M = { t: 16, r: 10, b: 26, l: 44 };
const PW = W - M.l - M.r, PH = H - M.t - M.b;

// Unidad, decimales y límites de cada indicador (los mismos que usa el motor para recortar).
// `high`/`low`: cortes de nivel 1, 2 y 3 copiados de risk/thresholds.json
// (`inclusive` igual que allí). Si cambian allí, hay que cambiarlos aquí.
const INDICATORS = {
  systolic_mmhg: { unit: "mmHg", digits: 0, high: [120, 140, 181], inclusive: true },
  diastolic_mmhg: { unit: "mmHg", digits: 0, high: [80, 90, 121], inclusive: true },
  glucose_mg_dl: { unit: "mg/dL", digits: 0, high: [99, 125, 250], low: [null, 70, 54] },
  mood: { unit: "/5", digits: 1, min: 1, max: 5, low: [3, 2, null] },
  pushup_reps: { unit: "reps", digits: 1, min: 0 },
};
const info = (name) => INDICATORS[name] ?? { unit: "", digits: 1 };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clamp = (v, lo, hi) => Math.min(hi ?? Infinity, Math.max(lo ?? -Infinity, v));
const xOf = (day) => M.l + ((day + DAYS) / (2 * DAYS)) * PW;
const dayLabel = (d) => (d === 0 ? "Today" : `${d > 0 ? "+" : "−"}${Math.abs(d)} d`);

/** Siguiente corte que la recta aún no ha pasado, en la dirección de la pendiente (como risk/trends.py). */
function nextCut(ind, current, slope) {
  const cuts = slope > 0 ? ind.high : slope < 0 ? ind.low : null;
  if (!cuts) return null;
  for (let i = 0; i < cuts.length; i++) {
    const cut = cuts[i];
    if (cut == null) continue;
    const crossed = slope > 0
      ? (ind.inclusive ? current >= cut : current > cut)
      : (ind.inclusive ? current <= cut : current < cut);
    if (!crossed) return { value: cut, level: i + 1 };
  }
  return null;
}

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

/** HTML de una tendencia: título, resumen y gráfica. `names` y `levelName` los pone app.js. */
export function trendChart(t, { names = {}, levelName = (l) => l } = {}) {
  const ind = info(t.indicator);
  const slope = Number(t.slope_per_day) || 0;
  const b = Number(t.projected_7d) - DAYS * slope;
  const value = (day) => clamp(b + slope * day, ind.min, ind.max);
  const fmt = (v) => Number(v).toFixed(ind.digits);
  const days = t.crosses_threshold_in_days;
  // Umbral que manda el motor (lo cruza en 7 días) o, si no hay, el siguiente que no alcanza.
  const far = t.threshold == null ? nextCut(ind, value(0), slope) : null;
  const threshold = t.threshold != null ? Number(t.threshold) : far ? far.value : null;
  const thLevel = t.threshold != null ? t.threshold_level : far?.level ?? null;
  const crosses = days != null && t.threshold != null;

  // Eje Y: la recta en −7, 0 y +7 y el umbral, con algo de aire.
  const vals = [value(-DAYS), value(0), value(DAYS)];
  if (threshold != null) vals.push(threshold);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.18, Math.abs(hi) * 0.02, 0.5);
  lo -= pad; hi += pad;
  if (ind.min != null) lo = Math.max(ind.min - 0.2, lo);
  if (ind.max != null) hi = Math.min(ind.max + 0.2, hi);
  const yOf = (v) => M.t + (1 - (v - lo) / (hi - lo)) * PH;

  const step = niceStep((hi - lo) / 3);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(6));

  const title = names[t.indicator] ?? t.indicator;
  const sign = slope > 0 ? "+" : slope < 0 ? "−" : "±";
  const headline = crosses
    ? `Reaches ${fmt(threshold)} ${ind.unit} (${levelName(thLevel)}) in ${days} d`
    : "No threshold crossed within 7 days";
  // Etiqueta del umbral: encima de la línea, o debajo si no cabe arriba.
  const thY = threshold == null ? 0 : yOf(threshold);
  const thLabelY = thY - M.t < 16 ? thY + 15 : thY - 7;
  const thText = `${levelName(thLevel).toUpperCase()} ${fmt(threshold)}${far ? " · NOT REACHED" : ""}`;

  // Puntos de la recta en pantalla
  const x0 = xOf(-DAYS), xN = xOf(0), x7 = xOf(DAYS);
  const y0 = yOf(value(-DAYS)), yN = yOf(value(0)), y7 = yOf(value(DAYS));
  const base = M.t + PH;
  const id = `tg-${t.indicator}`;
  // Esquinas tipo HUD, como las del cuerpo
  const k = 7, L = M.l - 4, R = W - M.r + 4, T = M.t - 6, B = base + 4;
  const hud = `M${L},${T + k}V${T}H${L + k} M${R - k},${T}H${R}V${T + k} M${L},${B - k}V${B}H${L + k} M${R - k},${B}H${R}V${B - k}`;

  return `<div class="trend" data-level="${thLevel ?? ""}">
    <p class="trend-label">${esc(title)}</p>
    <div class="trend-top">
      <p class="trend-val">${fmt(t.projected_7d)}<small>${esc(ind.unit)}</small></p>
      <p class="trend-meta">IN 7 DAYS<br>${sign}${Math.abs(slope)} ${esc(ind.unit)}/DAY</p>
    </div>
    <p class="trend-head ${crosses ? "warn" : ""}">${crosses ? `<i class="sw"></i>` : ""}${esc(headline)}</p>
    <div class="tplot">
      <svg class="tchart" viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${esc(title)}: ${esc(headline)}. Projected ${fmt(t.projected_7d)} ${esc(ind.unit)} in 7 days."
           data-b="${b}" data-m="${slope}" data-lo="${lo}" data-hi="${hi}" data-min="${ind.min ?? ""}" data-max="${ind.max ?? ""}"
           data-unit="${esc(ind.unit)}" data-digits="${ind.digits}">
        <defs>
          <linearGradient id="${id}-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="var(--accent)" stop-opacity=".28"/>
            <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
          </linearGradient>
          <linearGradient id="${id}-proj" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stop-color="var(--accent)" stop-opacity=".14"/>
            <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <path class="thud" d="${hud}"/>
        <rect class="tfuture" x="${xN}" y="${M.t}" width="${x7 - xN}" height="${PH}"/>
        <g class="tgrid">${ticks.map((v) => `<line x1="${M.l}" x2="${W - M.r}" y1="${yOf(v)}" y2="${yOf(v)}"/>`).join("")}</g>
        <g class="taxis">
          ${ticks.map((v) => `<text x="${M.l - 9}" y="${yOf(v)}" text-anchor="end" dominant-baseline="middle">${fmt(v)}</text>`).join("")}
          ${[-7, 0, 7].map((d) => `<text x="${xOf(d)}" y="${H - 6}" text-anchor="${d < 0 ? "start" : d > 0 ? "end" : "middle"}">${dayLabel(d).toUpperCase()}</text>`).join("")}
        </g>
        <line class="ttoday" x1="${xN}" x2="${xN}" y1="${M.t}" y2="${base}"/>
        ${threshold == null ? "" : `
          <line class="tthreshold${far ? " far" : ""}" x1="${M.l}" x2="${W - M.r}" y1="${thY}" y2="${thY}"/>
          <text class="tthreshold-label${far ? " far" : ""}" x="${crosses ? M.l + 4 : W - M.r}" y="${thLabelY}" text-anchor="${crosses ? "start" : "end"}">${esc(thText)}</text>`}
        <path class="tarea" d="M${x0},${y0} L${xN},${yN} L${xN},${base} L${x0},${base}Z" fill="url(#${id}-fill)"/>
        <path class="tarea" d="M${xN},${yN} L${x7},${y7} L${x7},${base} L${xN},${base}Z" fill="url(#${id}-proj)"/>
        <path class="tfit" d="M${x0},${y0} L${xN},${yN}"/>
        <path class="tproj" d="M${xN},${yN} L${x7},${y7}"/>
        <circle class="tpulse" cx="${xN}" cy="${yN}" r="4"/>
        <circle class="tnow" cx="${xN}" cy="${yN}" r="3.5"/>
        ${crosses ? `<circle class="tpulse lv" cx="${xOf(days)}" cy="${thY}" r="5"/><circle class="tcross" cx="${xOf(days)}" cy="${thY}" r="4"/>` : ""}
        <g class="thover" visibility="hidden"><line y1="${M.t}" y2="${base}"/><circle r="4"/></g>
        <rect class="thit" x="${M.l}" y="${M.t}" width="${PW}" height="${PH}"/>
      </svg>
      <div class="ttip" hidden></div>
    </div>
  </div>`;
}

/** Cruceta y tooltip para todas las gráficas que haya dentro de `root` (ahora o después). */
export function attachTrendHover(root) {
  const hideAll = () => {
    for (const g of root.querySelectorAll(".thover")) g.setAttribute("visibility", "hidden");
    for (const tip of root.querySelectorAll(".ttip")) tip.hidden = true;
  };
  const show = (e) => {
    const hit = e.target.closest?.(".thit");
    if (!hit) return hideAll();
    const svg = hit.ownerSVGElement, d = svg.dataset;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const day = clamp(Math.round((((p.x - M.l) / PW) * 2 * DAYS - DAYS) * 2) / 2, -DAYS, DAYS);
    const v = clamp(+d.b + +d.m * day, d.min === "" ? null : +d.min, d.max === "" ? null : +d.max);
    const x = xOf(day), y = M.t + (1 - (v - +d.lo) / (+d.hi - +d.lo)) * PH;

    hideAll();
    const g = svg.querySelector(".thover");
    g.setAttribute("visibility", "visible");
    g.querySelector("line").setAttribute("x1", x);
    g.querySelector("line").setAttribute("x2", x);
    g.querySelector("circle").setAttribute("cx", x);
    g.querySelector("circle").setAttribute("cy", y);

    const tip = svg.parentElement.querySelector(".ttip");
    const kind = day > 0 ? "projected" : day < 0 ? "7-day fit" : "now (fit)";
    tip.innerHTML = `<span>${dayLabel(day).toUpperCase()} · ${kind.toUpperCase()}</span><b>${v.toFixed(+d.digits)} ${esc(d.unit)}</b>`;
    tip.style.left = `${clamp((x / W) * 100, 18, 82)}%`;
    tip.style.top = `${(y / H) * 100}%`;
    tip.hidden = false;
  };
  root.addEventListener("pointermove", show);
  root.addEventListener("pointerdown", show);
  root.addEventListener("pointerleave", hideAll);
}
