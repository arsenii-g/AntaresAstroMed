// Planeta: un planeta de puntos visto desde órbita, con atmósfera,
// estrellas y una estación que cruza el horizonte. 3D hecho a mano sobre
// canvas 2D, sin librerías, para que funcione sin internet.

import { stage } from "./stage.js";

const N = 42000;        // puntos del planeta (solo se ve el casquete de arriba)
const STARS = 240;

// Opciones: horizon = altura del borde del planeta (0 arriba, 1 abajo),
// radius(w, h) = radio en px, parallax = seguir al ratón y al scroll.
export function createPlanet(canvas, { horizon = 0.76, radius = (w) => Math.max(w * 0.64, 560), parallax = true } = {}) {
  // Puntos repartidos por la esfera (espiral de Fibonacci)
  const px = new Float32Array(N), py = new Float32Array(N), pz = new Float32Array(N);
  const land = new Uint8Array(N);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const a = i * golden;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    px[i] = x; py[i] = y; pz[i] = z;
    // "Continentes": ruido barato con senos
    const f = Math.sin(x * 3.1 + 1.3) * Math.sin(y * 2.7 + 0.4)
            + Math.sin(z * 4.2 + x * 2.0) * 0.6
            + Math.sin(y * 6.3 + z * 3.1) * 0.35;
    land[i] = f > 0.12 ? 1 : 0;
  }

  const stars = Array.from({ length: STARS }, () => ({
    x: Math.random(), y: Math.random(), d: 0.2 + Math.random() * 0.8, p: Math.random() * 6.28,
  }));

  let mx = 0, my = 0, tx = 0, ty = 0;
  window.addEventListener("pointermove", (e) => {
    if (!parallax) return;
    tx = e.clientX / window.innerWidth - 0.5;
    ty = e.clientY / window.innerHeight - 0.5;
  }, { passive: true });

  stage(canvas, (ctx, w, h, t) => {
    mx += (tx - mx) * 0.04; my += (ty - my) * 0.04;
    const scroll = parallax ? Math.min(window.scrollY / h, 1.2) : 0;

    ctx.clearRect(0, 0, w, h);

    // Estrellas
    for (const s of stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * 1.3 + s.p);
      const x = ((s.x - mx * 0.03 * s.d) % 1 + 1) % 1 * w;
      const y = s.y * h * 0.8 - scroll * 90 * s.d - my * 14 * s.d;
      ctx.globalAlpha = 0.15 + 0.6 * s.d * tw;
      ctx.fillStyle = "#dfeaff";
      const r = s.d > 0.86 ? 1.6 : 1;
      ctx.fillRect(x, y, r, r);
    }

    // Planeta: enorme, solo asoma el casquete superior
    const R = radius(w, h);
    const cx = w / 2 - mx * 26;
    const cy = h * (horizon + scroll * 0.22) + R - my * 12;

    // Halo de atmósfera
    ctx.globalAlpha = 1;
    let g = ctx.createRadialGradient(cx, cy, R * 0.985, cx, cy, R * 1.085);
    g.addColorStop(0, "rgba(120,190,255,.55)");
    g.addColorStop(0.25, "rgba(110,150,255,.16)");
    g.addColorStop(1, "rgba(110,150,255,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.09, 0, 6.2832); ctx.fill();

    // Disco oscuro (tapa las estrellas) con un borde iluminado
    g = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R);
    g.addColorStop(0, "#04060b");
    g.addColorStop(0.82, "#071225");
    g.addColorStop(1, "#1d4b86");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.2832); ctx.fill();

    // Superficie: gira sobre el eje horizontal, como al sobrevolarla
    const a = t * 0.022, ca = Math.cos(a), sa = Math.sin(a);
    const tilt = 0.32, ct = Math.cos(tilt), st = Math.sin(tilt);
    const yMin = (cy - h) / R;                 // por debajo no se ve
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < N; i++) {
      // inclinación del eje (sobre Z) y giro (sobre X)
      const x0 = px[i] * ct - py[i] * st;
      const y0 = px[i] * st + py[i] * ct;
      const y = y0 * ca - pz[i] * sa;
      if (y < yMin) continue;
      const z = y0 * sa + pz[i] * ca;
      if (z < 0) continue;
      const sx = cx + x0 * R;
      if (sx < -4 || sx > w + 4) continue;
      const sy = cy - y * R;
      const limb = 1 - z;                      // 1 en el horizonte
      const isLand = land[i];
      ctx.globalAlpha = (isLand ? 0.5 : 0.13) * (0.35 + limb * limb * 1.6);
      ctx.fillStyle = isLand ? "#9fe0ff" : "#5d8bff";
      const s = isLand ? 1.7 : 1.1;
      ctx.fillRect(sx, sy, s, s * (0.45 + z * 0.55));   // se aplastan cerca del horizonte
    }

    // Órbita y estación
    const Ro = R * 1.045;
    ctx.globalAlpha = 0.22;
    ctx.strokeStyle = "#8fd8ff";
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 9]);
    ctx.beginPath(); ctx.arc(cx, cy, Ro, 0, 6.2832); ctx.stroke();
    ctx.setLineDash([]);

    const span = Math.asin(Math.min(1, (w * 0.5 + 80) / Ro));
    const phi = -span + ((t * 0.035) % 1) * span * 2;
    for (let k = 0; k < 26; k++) {             // estela
      const p = phi - k * 0.004;
      ctx.globalAlpha = 0.5 * (1 - k / 26);
      ctx.fillStyle = "#8fd8ff";
      ctx.fillRect(cx + Math.sin(p) * Ro, cy - Math.cos(p) * Ro, 2, 2);
    }
    const sx = cx + Math.sin(phi) * Ro, sy = cy - Math.cos(phi) * Ro;
    g = ctx.createRadialGradient(sx, sy, 0, sx, sy, 16);
    g.addColorStop(0, "rgba(255,255,255,.95)");
    g.addColorStop(0.2, "rgba(143,216,255,.5)");
    g.addColorStop(1, "rgba(143,216,255,0)");
    ctx.globalAlpha = 1;
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(sx, sy, 16, 0, 6.2832); ctx.fill();

    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 0.95;
    ctx.fillStyle = "#8fd8ff";
    ctx.font = '500 12.5px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillText("ARGOS-1", sx + 14, sy - 10);
    ctx.globalAlpha = 1;
  });
}
