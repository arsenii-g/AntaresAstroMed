// Gráfica de un elemento de `trends` (contrato ③), tal como lo manda el motor
// (risk/trends.py). No se calcula ni se copia nada aquí: los puntos medidos, la
// recta (slope, intercept), el horizonte y el umbral vienen en el mensaje.
//
//   basis "count": x = número de medida (último chequeo o serie = 0, el
//                  anterior = −1…); se proyecta `horizon` medidas más.
//   basis "time":  x = segundos respecto a la evaluación; se proyecta
//                  `horizon` segundos.
//
// Línea continua: ajuste sobre las medidas. Punteada: proyección. Discontinua
// de color: el siguiente umbral en la dirección de la pendiente, si hay.

const W = 320, H = 150;
const M = { t: 16, r: 10, b: 26, l: 44 };
const PW = W - M.l - M.r, PH = H - M.t - M.b;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clamp = (v, lo, hi) => Math.min(hi ?? Infinity, Math.max(lo ?? -Infinity, v));
const NOUN = { check: ["check", "checks"], set: ["set", "sets"], s: ["s", "s"] };
const plural = (n, unit) => (NOUN[unit] ?? [unit, unit])[Math.abs(n) === 1 ? 0 : 1];

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

/** Texto de x: "−6 checks", "Last", "+7 checks"; "−60 s", "Now", "+60 s". */
function xLabel(x, t) {
  if (x === 0) return t.basis === "time" ? "Now" : "Last";
  const n = Math.round(Math.abs(x));
  return `${x > 0 ? "+" : "−"}${n}${t.basis === "time" ? " s" : ` ${plural(n, t.x_unit)}`}`;
}

/** Cuándo cruza: "in 12 s" o "in about 3 checks". */
export function crossText(t) {
  if (t.crosses_in == null) return "";
  if (t.basis === "time") return `in ${Math.round(t.crosses_in)} s`;
  const n = Math.max(1, Math.ceil(t.crosses_in));
  return `in about ${n} more ${plural(n, t.x_unit)}`;
}

/** HTML de una tendencia: título, resumen y gráfica. `levelName` lo pone app.js. */
export function trendChart(t, { levelName = (l) => l } = {}) {
  const points = (t.points ?? []).filter((p) => Array.isArray(p) && p.every(Number.isFinite));
  const slope = Number(t.slope) || 0, b = Number(t.intercept) || 0;
  const horizon = Number(t.horizon) || 0;
  const unit = t.unit ?? "";
  const line = (x) => b + slope * x;
  const values = points.map((p) => p[1]);

  const x0 = Math.min(...points.map((p) => p[0]), t.basis === "time" ? -60 : -1);
  const xOf = (x) => M.l + ((x - x0) / (horizon - x0)) * PW;
  const threshold = t.threshold == null ? null : Number(t.threshold);
  const crosses = t.crosses_in != null && threshold != null;

  // Eje Y: medidas, recta en los extremos y umbral, con algo de aire.
  const vals = [...values, line(x0), line(0), line(horizon)];
  if (threshold != null) vals.push(threshold);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.18, Math.abs(hi) * 0.02, 0.5);
  lo -= pad; hi += pad;
  const yOf = (v) => M.t + (1 - (clamp(v, lo, hi) - lo) / (hi - lo)) * PH;
  // Sin decimales en escalas amplias de enteros (pulso, tensión); con uno en el resto.
  const digits = values.every((v) => Number.isInteger(v)) && hi - lo >= 10 ? 0 : 1;
  const fmt = (v) => Number(v).toFixed(digits);

  const step = niceStep((hi - lo) / 3);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(6));

  const per = t.basis === "time" ? "S" : (NOUN[t.x_unit]?.[0] ?? t.x_unit).toUpperCase();
  const sign = slope > 0 ? "+" : slope < 0 ? "−" : "±";
  const rate = Math.abs(slope) < 0.01 && slope !== 0 ? Math.abs(slope).toExponential(1) : Math.abs(slope).toFixed(2);
  const headline = crosses
    ? `Reaches ${fmt(threshold)} ${unit} (${levelName(t.threshold_level)}) ${crossText(t)}`
    : threshold != null ? `Does not reach ${fmt(threshold)} ${unit} within ${xLabel(horizon, t).slice(1)}`
    : "No further threshold in this direction";
  const thY = threshold == null ? 0 : yOf(threshold);
  const thLabelY = thY - M.t < 16 ? thY + 15 : thY - 7;
  const thText = `${levelName(t.threshold_level).toUpperCase()} ${fmt(threshold)}${crosses ? "" : " · NOT REACHED"}`;

  const xs = xOf(x0), xN = xOf(0), xH = xOf(horizon);
  const ys = yOf(line(x0)), yN = yOf(line(0)), yH = yOf(line(horizon));
  const base = M.t + PH;
  const id = `tg-${esc(t.indicator)}`;
  const k = 7, L = M.l - 4, R = W - M.r + 4, T = M.t - 6, B = base + 4;
  const hud = `M${L},${T + k}V${T}H${L + k} M${R - k},${T}H${R}V${T + k} M${L},${B - k}V${B}H${L + k} M${R - k},${B}H${R}V${B - k}`;
  const crossX = crosses ? xOf(Number(t.crosses_in)) : 0;
  const xTicks = [x0, 0, horizon];

  return `<div class="trend" data-level="${crosses ? t.threshold_level ?? "" : ""}">
    <p class="trend-label">${esc(t.label ?? t.indicator)} · ${points.length} readings</p>
    <div class="trend-top">
      <p class="trend-val">${fmt(t.projected)}<small>${esc(unit)}</small></p>
      <p class="trend-meta">IN ${esc(xLabel(horizon, t).slice(1).toUpperCase())}<br>${sign}${rate} ${esc(unit)}/${esc(per)}</p>
    </div>
    <p class="trend-head ${crosses ? "warn" : ""}">${crosses ? `<i class="sw"></i>` : ""}${esc(headline)}</p>
    <div class="tplot">
      <svg class="tchart" viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${esc(t.label ?? t.indicator)}: ${esc(headline)}."
           data-b="${b}" data-m="${slope}" data-lo="${lo}" data-hi="${hi}" data-x0="${x0}" data-h="${horizon}"
           data-basis="${esc(t.basis)}" data-xunit="${esc(t.x_unit)}" data-unit="${esc(unit)}" data-digits="${digits}">
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
        <rect class="tfuture" x="${xN}" y="${M.t}" width="${xH - xN}" height="${PH}"/>
        <g class="tgrid">${ticks.map((v) => `<line x1="${M.l}" x2="${W - M.r}" y1="${yOf(v)}" y2="${yOf(v)}"/>`).join("")}</g>
        <g class="taxis">
          ${ticks.map((v) => `<text x="${M.l - 9}" y="${yOf(v)}" text-anchor="end" dominant-baseline="middle">${fmt(v)}</text>`).join("")}
          ${xTicks.map((x, i) => `<text x="${xOf(x)}" y="${H - 6}" text-anchor="${["start", "middle", "end"][i]}">${esc(xLabel(x, t).toUpperCase())}</text>`).join("")}
        </g>
        <line class="ttoday" x1="${xN}" x2="${xN}" y1="${M.t}" y2="${base}"/>
        ${threshold == null ? "" : `
          <line class="tthreshold${crosses ? "" : " far"}" x1="${M.l}" x2="${W - M.r}" y1="${thY}" y2="${thY}"/>
          <text class="tthreshold-label${crosses ? "" : " far"}" x="${crosses ? M.l + 4 : W - M.r}" y="${thLabelY}" text-anchor="${crosses ? "start" : "end"}">${esc(thText)}</text>`}
        <path class="tarea" d="M${xs},${ys} L${xN},${yN} L${xN},${base} L${xs},${base}Z" fill="url(#${id}-fill)"/>
        <path class="tarea" d="M${xN},${yN} L${xH},${yH} L${xH},${base} L${xN},${base}Z" fill="url(#${id}-proj)"/>
        <path class="tfit" d="M${xs},${ys} L${xN},${yN}"/>
        <path class="tproj" d="M${xN},${yN} L${xH},${yH}"/>
        ${points.map(([x, v]) => `<circle class="tobserved" cx="${xOf(x)}" cy="${yOf(v)}" r="${points.length > 15 ? 2 : 3}" fill="var(--ink)" stroke="#080a10"><title>Measured ${fmt(v)} ${esc(unit)} · ${esc(xLabel(x, t))}</title></circle>`).join("")}
        <circle class="tpulse" cx="${xN}" cy="${yN}" r="4"/>
        <circle class="tnow" cx="${xN}" cy="${yN}" r="3.5"/>
        ${crosses ? `<circle class="tpulse lv" cx="${crossX}" cy="${thY}" r="5"/><circle class="tcross" cx="${crossX}" cy="${thY}" r="4"/>` : ""}
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
    const x0 = +d.x0, h = +d.h;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const x = clamp(Math.round(x0 + ((p.x - M.l) / PW) * (h - x0)), x0, h);
    const v = +d.b + +d.m * x;
    const sx = M.l + ((x - x0) / (h - x0)) * PW;
    const sy = M.t + (1 - (clamp(v, +d.lo, +d.hi) - +d.lo) / (+d.hi - +d.lo)) * PH;

    hideAll();
    const g = svg.querySelector(".thover");
    g.setAttribute("visibility", "visible");
    g.querySelector("line").setAttribute("x1", sx);
    g.querySelector("line").setAttribute("x2", sx);
    g.querySelector("circle").setAttribute("cx", sx);
    g.querySelector("circle").setAttribute("cy", sy);

    const tip = svg.parentElement.querySelector(".ttip");
    const kind = x > 0 ? "projected" : "fit";
    const label = xLabel(x, { basis: d.basis, x_unit: d.xunit });
    tip.innerHTML = `<span>${esc(label.toUpperCase())} · ${kind.toUpperCase()}</span><b>${v.toFixed(+d.digits)} ${esc(d.unit)}</b>`;
    tip.style.left = `${clamp((sx / W) * 100, 18, 82)}%`;
    tip.style.top = `${(sy / H) * 100}%`;
    tip.hidden = false;
  };
  root.addEventListener("pointermove", show);
  root.addEventListener("pointerdown", show);
  root.addEventListener("pointerleave", hideAll);
}
