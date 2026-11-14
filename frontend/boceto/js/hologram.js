// Cuerpo holográfico de la consola: una figura hecha de anillos de puntos,
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

// Partes del cuerpo como elipsoides: centro, radios y sistema al que pertenecen.
// Unidades: la figura mide unos 2 de alto, con Y hacia arriba.
const C = "cardiovascular", NE = "neuro", M = "musculoskeletal";
const PARTS = [
  { c: [0, 0.80, 0], r: [0.125, 0.155, 0.14], s: NE },          // cabeza
  { c: [0, 0.61, 0], r: [0.055, 0.07, 0.055], s: NE },          // cuello
  { c: [0, 0.36, 0], r: [0.235, 0.21, 0.13], s: C },            // pecho
  { c: [0, 0.08, 0], r: [0.19, 0.17, 0.115], s: C },            // abdomen
  { c: [0, -0.13, 0], r: [0.205, 0.11, 0.12], s: M },           // cadera
  ...[-1, 1].flatMap((k) => [
    { c: [0.27 * k, 0.5, 0], r: [0.085, 0.075, 0.085], s: M },  // hombro
    { c: [0.33 * k, 0.3, 0], r: [0.06, 0.2, 0.062], s: M },     // brazo
    { c: [0.385 * k, -0.02, 0.02], r: [0.048, 0.19, 0.05], s: M }, // antebrazo
    { c: [0.41 * k, -0.25, 0.04], r: [0.04, 0.07, 0.03], s: M },   // mano
    { c: [0.11 * k, -0.42, 0], r: [0.092, 0.27, 0.095], s: M },    // muslo
    { c: [0.12 * k, -0.86, -0.01], r: [0.065, 0.22, 0.07], s: M }, // pierna
    { c: [0.125 * k, -1.07, 0.05], r: [0.05, 0.03, 0.1], s: M },   // pie
  ]),
];

// Dónde apunta cada etiqueta y a qué lado se escribe
const TAGS = [
  { s: NE, at: [0.1, 0.84, 0.05], side: 1, text: "NEURO" },
  { s: C, at: [-0.14, 0.38, 0.08], side: -1, text: "CARDIO" },
  { s: M, at: [0.17, -0.5, 0.05], side: 1, text: "MUSCULO" },
  { s: "environment", at: [-0.62, -1.12, 0], side: -1, text: "CABIN" },
];

export function createHologram(canvas, { onPick } = {}) {
  // Puntos: cada parte se corta en rebanadas horizontales (curvas de nivel)
  const pts = [];
  const STEP = 0.026;
  for (const p of PARTS) {
    const [cx, cy, cz] = p.c, [rx, ry, rz] = p.r;
    for (let y = cy - ry + STEP / 2; y < cy + ry; y += STEP) {
      const k = Math.sqrt(Math.max(0, 1 - ((y - cy) / ry) ** 2));
      const n = Math.max(5, Math.round((Math.PI * (rx + rz) * k) / 0.021));
      const off = (y * 37) % 1;
      for (let i = 0; i < n; i++) {
        const a = ((i + off) / n) * 6.2832;
        pts.push([cx + Math.cos(a) * rx * k, y, cz + Math.sin(a) * rz * k, SYSTEMS.indexOf(p.s)]);
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
    ctx.font = '10px "JetBrains Mono", ui-monospace, monospace';
    ctx.lineWidth = 1;
    for (const tag of TAGS) {
      const i = SYSTEMS.indexOf(tag.s);
      const [ax, ay] = view(...tag.at);
      const lx = w / 2 + tag.side * Math.min(w * 0.4, scale * 0.95);
      const lv = levels[tag.s];
      ctx.globalAlpha = 0.85 * dimOf(i);
      ctx.strokeStyle = ctx.fillStyle = css[i];
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(lx - tag.side * 14, ay - 18); ctx.lineTo(lx, ay - 18); ctx.stroke();
      ctx.beginPath(); ctx.arc(ax, ay, 2.5, 0, 6.2832); ctx.fill();
      ctx.textAlign = tag.side > 0 ? "right" : "left";
      ctx.fillText(tag.text, lx, ay - 24);
      ctx.globalAlpha *= 0.7;
      ctx.fillText(lv == null ? "NO DATA" : `LEVEL ${lv}`, lx, ay - 6);
    }
    ctx.globalAlpha = 1;
  });

  return {
    setLevels(next) { Object.assign(levels, next); scene.redraw(); },
    setFocus(system) { focus = system; scene.redraw(); },
    setBpm(n) { if (typeof n === "number" && n > 0) bpm = n; },
  };
}
