// Cuerpo holográfico de la consola: una figura de cilindros redondeados hecha de anillos de puntos,
// coloreada por sistema según el nivel de riesgo (contrato ③).
//
//   const holo = createHologram(canvas, { onPick: (system) => ... });
//   holo.setLevels({ cardiovascular: 1, neuro: 0, musculoskeletal: null, environment: 2 });
//   holo.setFocus("cardiovascular");   // o null para ver todo
//   holo.setBpm(72);                   // ritmo del latido
//
// Es un boceto: se puede cambiar por el SVG clicable o por un modelo real
// sin tocar app.js, mientras se mantengan esas cuatro funciones.

import { stage } from "./stage.js";

const RGB = {
  0: [94, 242, 192], 1: [255, 200, 87], 2: [255, 138, 61], 3: [255, 77, 109], null: [107, 116, 136],
};
const SYSTEMS = ["cardiovascular", "neuro", "musculoskeletal", "environment"];

// Partes del cuerpo como cilindros redondeados (cápsulas que se estrechan):
// eje de `a` a `b`, radio `r` en cada extremo (o un perfil `prof` de pares
// [t, radio] a lo largo del eje) y sección elíptica con `sx`/`sz`.
// `cap` redondea los extremos [a, b]; `capY` aplana esa tapa.
// Unidades: la figura mide unos 2 de alto, con Y hacia arriba.
const C = "cardiovascular", NE = "neuro", M = "musculoskeletal";
const PARTS = [
  { a: [0, 0.75, 0], b: [0, 0.85, 0], r: [0.112, 0.112], sz: 1.12, cap: [1, 1], s: NE },        // cabeza
  { a: [0, 0.55, -0.005], b: [0, 0.69, 0], r: [0.056, 0.05], s: NE },                           // cuello
  { a: [0, 0.04, 0], b: [0, 0.57, 0], sz: 0.56, cap: [0, 1], capY: 0.35, s: C,                  // tronco
    prof: [[0, 0.178], [0.25, 0.172], [0.5, 0.205], [0.72, 0.232], [0.88, 0.228], [1, 0.175]] },
  { a: [0, -0.21, 0], b: [0, 0.04, 0], sz: 0.6, cap: [1, 0], capY: 0.45, s: M,                  // cadera
    prof: [[0, 0.19], [0.55, 0.205], [1, 0.18]] },
  ...[-1, 1].flatMap((k) => [
    { a: [0.255 * k, 0.5, 0], b: [0.335 * k, 0.13, 0], r: [0.078, 0.056], cap: [1, 1], s: M },      // hombro y brazo
    { a: [0.335 * k, 0.13, 0], b: [0.39 * k, -0.19, 0.035], r: [0.054, 0.04], cap: [1, 1], s: M }, // antebrazo
    { a: [0.39 * k, -0.2, 0.035], b: [0.405 * k, -0.3, 0.045], r: [0.04, 0.032], sz: 0.75, cap: [1, 1], s: M }, // mano
    { a: [0.105 * k, -0.17, 0], b: [0.12 * k, -0.65, 0], r: [0.1, 0.066], cap: [1, 1], s: M },      // muslo
    { a: [0.12 * k, -0.65, 0], b: [0.125 * k, -1.03, -0.01], r: [0.066, 0.044], cap: [1, 1], s: M }, // pierna
    { a: [0.125 * k, -1.075, -0.03], b: [0.125 * k, -1.085, 0.12], r: [0.044, 0.036], sx: 1.05, cap: [1, 1], capY: 0.8, s: M }, // pie
  ]),
].map(prepare);

// Vectores de cada parte: eje, base perpendicular, centro y radio en cada punto del eje.
function prepare(p) {
  const d = p.b.map((v, i) => v - p.a[i]);
  const len = Math.hypot(...d) || 1e-6;
  const w = d.map((v) => v / len);
  const ref = Math.abs(w[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
  let u = [w[1] * ref[2] - w[2] * ref[1], w[2] * ref[0] - w[0] * ref[2], w[0] * ref[1] - w[1] * ref[0]];
  const ul = Math.hypot(...u); u = u.map((v) => v / ul);
  const v = [w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2], w[0] * u[1] - w[1] * u[0]];
  const prof = p.prof ?? [[0, p.r[0]], [1, p.r[1]]];
  const radius = (t) => {                     // interpolación suave entre estaciones del perfil
    t = Math.min(1, Math.max(0, t));
    let i = 0; while (i < prof.length - 2 && t > prof[i + 1][0]) i++;
    const [t0, r0] = prof[i], [t1, r1] = prof[i + 1];
    const f = (t - t0) / (t1 - t0 || 1), e = f * f * (3 - 2 * f);
    return r0 + (r1 - r0) * e;
  };
  return {
    ...p, len, w, u, v, radius, sx: p.sx ?? 1, sz: p.sz ?? 1, cap: p.cap ?? [0, 0], capY: p.capY ?? 1,
    c: p.a.map((x, i) => x + d[i] / 2),
  };
}

// ¿Está el punto dentro de la parte? Sirve para no dibujar los puntos que quedan
// tapados donde se unen dos partes, y que la figura parezca una sola pieza.
function inside(p, [x, y, z], margin = 0.94) {
  // Se deshace la sección elíptica y se mide respecto al extremo `a`
  const q = [(x - p.c[0]) / p.sx + p.c[0] - p.a[0], y - p.a[1], (z - p.c[2]) / p.sz + p.c[2] - p.a[2]];
  const ax = q[0] * p.w[0] + q[1] * p.w[1] + q[2] * p.w[2];        // posición a lo largo del eje
  const radial = Math.hypot(q[0] - p.w[0] * ax, q[1] - p.w[1] * ax, q[2] - p.w[2] * ax);
  const t = ax / p.len;
  if (t >= 0 && t <= 1) return radial < p.radius(t) * margin;
  const end = t > 1 ? 1 : 0;
  if (!p.cap[end]) return false;
  const axial = (end ? ax - p.len : ax) / p.capY;                 // tapa: media esfera (aplanada)
  return Math.hypot(radial, axial) < p.radius(end) * margin;
}

// Dónde apunta cada etiqueta y a qué lado se escribe
const TAGS = [
  { s: NE, at: [0.1, 0.84, 0.05], side: 1, text: "NEURO" },
  { s: C, at: [-0.14, 0.38, 0.08], side: -1, text: "CARDIO" },
  { s: M, at: [0.17, -0.5, 0.05], side: 1, text: "MUSCULO" },
  { s: "environment", at: [-0.62, -1.12, 0], side: -1, text: "CABIN" },
];

export function createHologram(canvas, { onPick } = {}) {
  // Puntos: cada parte se corta en anillos perpendiculares a su eje (curvas de
  // nivel), con muchos puntos por anillo para que la sección se vea redonda.
  const pts = [];
  const STEP = 0.024, GAP = 0.017;
  const addRing = (p, along, r, si, twist) => {
    const n = Math.max(r < 0.025 ? 6 : 18, Math.round((2 * Math.PI * r * (p.sx + p.sz)) / 2 / GAP));
    for (let i = 0; i < n; i++) {
      const ang = ((i + twist) / n) * 6.2832, ca = Math.cos(ang) * r, sa = Math.sin(ang) * r;
      const pt = [0, 1, 2].map((j) => p.a[j] + p.w[j] * along + p.u[j] * ca + p.v[j] * sa);
      pt[0] = p.c[0] + (pt[0] - p.c[0]) * p.sx;      // sección elíptica
      pt[2] = p.c[2] + (pt[2] - p.c[2]) * p.sz;
      if (PARTS.some((o) => o !== p && inside(o, pt))) continue;
      pts.push([...pt, si]);
    }
  };
  for (const p of PARTS) {
    const si = SYSTEMS.indexOf(p.s);
    const rings = Math.max(2, Math.round(p.len / STEP));
    for (let k = 0; k <= rings; k++) addRing(p, (k / rings) * p.len, p.radius(k / rings), si, (k * 0.37) % 1);
    // Tapas redondas: anillos que se cierran sobre una media esfera
    for (const end of [0, 1]) {
      if (!p.cap[end]) continue;
      const r0 = p.radius(end), steps = Math.max(2, Math.round((Math.PI / 2) * r0 * p.capY / STEP));
      for (let k = 1; k <= steps; k++) {
        const phi = (k / steps) * (Math.PI / 2) * 0.96;
        const off = Math.sin(phi) * r0 * p.capY;
        addRing(p, end ? p.len + off : -off, r0 * Math.cos(phi), si, (k * 0.53) % 1);
      }
    }
  }
  // Suelo: dos anillos que representan la cabina (sistema "environment")
  const ENV = SYSTEMS.indexOf("environment");
  const ring = [];
  for (let i = 0; i < 120; i++) ring.push([Math.cos(i / 120 * 6.2832) * 0.62, Math.sin(i / 120 * 6.2832) * 0.62, 0]);
  for (let i = 0; i < 64; i++) if (i % 4 !== 3) ring.push([Math.cos(i / 64 * 6.2832) * 0.84, Math.sin(i / 64 * 6.2832) * 0.84, 1]);

  const levels = Object.fromEntries(SYSTEMS.map((s) => [s, null]));
  const color = SYSTEMS.map(() => [...RGB.null]);     // color actual, se acerca al del nivel
  let focus = null, bpm = 70, beatPhase = 0, lastT = 0;
  let angle = 0.5, spin = 0.25, dragging = false, moved = 0, lastX = 0;
  let view = null;                                     // proyección del último fotograma

  canvas.addEventListener("pointerdown", (e) => { dragging = true; moved = 0; lastX = e.clientX; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX; lastX = e.clientX; moved += Math.abs(dx);
    angle += dx * 0.01; spin = 0;
  });
  canvas.addEventListener("pointerup", (e) => {
    dragging = false; spin = 0.25;
    if (moved > 5 || !view || !onPick) return;        // fue un arrastre, no un clic
    const b = canvas.getBoundingClientRect();
    const x = e.clientX - b.left, y = e.clientY - b.top;
    let best = null, bestD = 60;
    for (const p of PARTS) {
      const [sx, sy] = view(p.c[0], p.c[1], p.c[2]);
      const d = Math.hypot(sx - x, sy - y);
      if (d < bestD) { bestD = d; best = p.s; }
    }
    const [fx, fy] = view(0, -1.12, 0);
    if (!best && Math.abs(y - fy) < 40 && Math.abs(x - fx) < 200) best = "environment";
    onPick(best);
  });

  const scene = stage(canvas, (ctx, w, h, t) => {
    const dt = Math.min(t - lastT, 0.05); lastT = t;
    if (!dragging) angle += spin * dt;
    beatPhase += dt * bpm / 60;

    for (let i = 0; i < SYSTEMS.length; i++) {
      const target = RGB[levels[SYSTEMS[i]]] ?? RGB.null;
      for (let k = 0; k < 3; k++) color[i][k] += (target[k] - color[i][k]) * 0.07;
    }
    const css = color.map((c) => `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`);
    const dimOf = (i) => (focus && SYSTEMS[i] !== focus ? 0.22 : 1);

    const ca = Math.cos(angle), sa = Math.sin(angle);
    const scale = Math.min(h * 0.4, w * 0.8), D = 4.2;
    view = (x, y, z) => {
      const xr = x * ca + z * sa, zr = -x * sa + z * ca;
      const k = D / (D - zr);
      return [w / 2 + xr * scale * k, h * 0.49 - (y + 0.1) * scale * k, zr, k];
    };

    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";

    // Cabina: anillos en el suelo
    ctx.fillStyle = css[ENV];
    for (const [x, z, outer] of ring) {
      const a2 = outer ? -t * 0.15 : t * 0.08, c2 = Math.cos(a2), s2 = Math.sin(a2);
      const [sx, sy, zr] = view(x * c2 - z * s2, -1.12, x * s2 + z * c2);
      ctx.globalAlpha = (0.3 + 0.5 * (zr + 0.9) / 1.8) * dimOf(ENV);
      ctx.fillRect(sx, sy, outer ? 2.4 : 1.6, 1.4);
    }
    // Haz de luz desde el suelo
    const [bx, by] = view(0, -1.12, 0);
    let g = ctx.createRadialGradient(bx, by, 0, bx, by, scale * 1.5);
    g.addColorStop(0, `rgba(${color[ENV].map((v) => v | 0)},.16)`);
    g.addColorStop(1, `rgba(${color[ENV].map((v) => v | 0)},0)`);
    ctx.globalAlpha = dimOf(ENV);
    ctx.fillStyle = g;
    ctx.save();
    ctx.translate(bx, by); ctx.scale(0.42, 1); ctx.translate(-bx, -by);   // elipse alta y estrecha
    ctx.beginPath(); ctx.arc(bx, by, scale * 1.5, Math.PI, 0); ctx.fill();
    ctx.restore();

    // Figura, con una línea de escáner que sube
    const scan = -1.15 + ((t * 0.22) % 1) * 2.2;
    let last = -1;
    for (const [x, y, z, s] of pts) {
      const [sx, sy, zr, k] = view(x, y, z);
      if (s !== last) { ctx.fillStyle = css[s]; last = s; }
      const depth = 0.3 + 0.7 * Math.min(1, Math.max(0, (zr + 0.25) / 0.5));
      const d = (y - scan) / 0.045;
      const glow = Math.exp(-d * d);
      ctx.globalAlpha = Math.min(1, (0.2 + 0.55 * depth + glow * 0.9) * dimOf(s));
      const size = (1.25 + glow * 1.3) * k;
      ctx.fillRect(sx, sy, size, size);
    }

    // Corazón: late al ritmo del pulso real
    const CV = SYSTEMS.indexOf(C);
    const beat = Math.pow(Math.max(0, Math.sin(beatPhase * 6.2832)), 10);
    const [hx, hy] = view(-0.055, 0.42, 0.06);
    const hr = scale * (0.07 + beat * 0.07);
    g = ctx.createRadialGradient(hx, hy, 0, hx, hy, hr);
    g.addColorStop(0, `rgba(${color[CV].map((v) => v | 0)},${0.55 + beat * 0.4})`);
    g.addColorStop(1, `rgba(${color[CV].map((v) => v | 0)},0)`);
    ctx.globalAlpha = dimOf(CV);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(hx, hy, hr, 0, 6.2832); ctx.fill();

    // Etiquetas con línea guía
    ctx.globalCompositeOperation = "source-over";
    const big = Math.min(15, Math.max(13, w / 60));    // las etiquetas crecen un poco con el lienzo
    ctx.lineWidth = 1.2;
    for (const tag of TAGS) {
      const i = SYSTEMS.indexOf(tag.s);
      const [ax, ay] = view(...tag.at);
      const lx = w / 2 + tag.side * Math.min(w * 0.4, scale * 0.95);
      const lv = levels[tag.s];
      ctx.globalAlpha = dimOf(i);
      ctx.strokeStyle = ctx.fillStyle = css[i];
      const ly = Math.max(big + 46, ay - 18);              // sin pisar el texto de ayuda de arriba
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(lx - tag.side * 14, ly); ctx.lineTo(lx, ly); ctx.stroke();
      ctx.beginPath(); ctx.arc(ax, ay, 2.5, 0, 6.2832); ctx.fill();
      ctx.textAlign = tag.side > 0 ? "right" : "left";
      ctx.font = `600 ${big}px "JetBrains Mono", ui-monospace, monospace`;
      ctx.fillText(tag.text, lx, ly - 7);
      ctx.globalAlpha *= 0.85;
      ctx.font = `500 ${big - 1}px "JetBrains Mono", ui-monospace, monospace`;
      ctx.fillText(lv == null ? "NO DATA" : `LEVEL ${lv}`, lx, ly + 15);
    }
    ctx.globalAlpha = 1;
  });

  return {
    setLevels(next) { Object.assign(levels, next); scene.redraw(); },
    setFocus(system) { focus = system; scene.redraw(); },
    setBpm(n) { if (typeof n === "number" && n > 0) bpm = n; },
  };
}
