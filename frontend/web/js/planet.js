// Planet: a dot-based planet seen from orbit, with atmosphere,
// stars, and the star Antares crossing the horizon. Hand-made 3D on a
// 2D canvas, with no libraries, so it works offline.

import { stage } from "./stage.js";

const N = 42000;        // planet points (only the top cap is visible)
const STARS = 240;

// Colors. The orbiting star is Antares: amber and rust tones, soft and without
// flicker, so it is not confused with the pinkish red of alerts (--lv3).
const ANTARES_STAR = { core: "255,243,224", glow: "255,150,96", trail: "#ffb48a", label: "#ffc4a3" };
export const PALETTES = {
  // Console: the usual blue planet; only the star is reddish.
  blue: {
    star: "#dfeaff", atmo: ["120,190,255", "110,150,255"], disc: ["#04060b", "#071225", "#1d4b86"],
    land: "#9fe0ff", sea: "#5d8bff", orbit: "#8fd8ff", station: ANTARES_STAR,
  },
  // Landing page: everything in the Antares palette.
  antares: {
    star: "#ffe9dc", atmo: ["255,140,90", "214,84,52"], disc: ["#070405", "#1a0a08", "#7a2a17"],
    land: "#ffc89e", sea: "#d6603a", orbit: "#ffb48a", station: ANTARES_STAR,
  },
};

// Options: horizon = height of the planet's edge (0 top, 1 bottom),
// radius(w, h) = radius in px, parallax = follow the mouse and scroll.
export function createPlanet(canvas, { horizon = 0.76, radius = (w) => Math.max(w * 0.64, 560), parallax = true, palette = PALETTES.blue, label = "ANTARES" } = {}) {
  const P = palette;
  // Points spread over the sphere (Fibonacci spiral)
  const px = new Float32Array(N), py = new Float32Array(N), pz = new Float32Array(N);
  const land = new Uint8Array(N);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const a = i * golden;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    px[i] = x; py[i] = y; pz[i] = z;
    // "Continents": cheap sine-based noise
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

    // Stars
    for (const s of stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * 1.3 + s.p);
      const x = ((s.x - mx * 0.03 * s.d) % 1 + 1) % 1 * w;
      const y = s.y * h * 0.8 - scroll * 90 * s.d - my * 14 * s.d;
      ctx.globalAlpha = 0.15 + 0.6 * s.d * tw;
      ctx.fillStyle = P.star;
      const r = s.d > 0.86 ? 1.6 : 1;
      ctx.fillRect(x, y, r, r);
    }

    // Planet: huge, only the top cap shows
    const R = radius(w, h);
    const cx = w / 2 - mx * 26;
    const cy = h * (horizon + scroll * 0.22) + R - my * 12;

    // Atmosphere halo
    ctx.globalAlpha = 1;
    let g = ctx.createRadialGradient(cx, cy, R * 0.985, cx, cy, R * 1.085);
    g.addColorStop(0, `rgba(${P.atmo[0]},.55)`);
    g.addColorStop(0.25, `rgba(${P.atmo[1]},.16)`);
    g.addColorStop(1, `rgba(${P.atmo[1]},0)`);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.09, 0, 6.2832); ctx.fill();

    // Dark disc (covers the stars) with a lit rim
    g = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R);
    g.addColorStop(0, P.disc[0]);
    g.addColorStop(0.82, P.disc[1]);
    g.addColorStop(1, P.disc[2]);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.2832); ctx.fill();

    // Surface: rotates about the horizontal axis, as if flying over it
    const a = t * 0.022, ca = Math.cos(a), sa = Math.sin(a);
    const tilt = 0.32, ct = Math.cos(tilt), st = Math.sin(tilt);
    const yMin = (cy - h) / R;                 // not visible below this
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < N; i++) {
      // axis tilt (about Z) and spin (about X)
      const x0 = px[i] * ct - py[i] * st;
      const y0 = px[i] * st + py[i] * ct;
      const y = y0 * ca - pz[i] * sa;
      if (y < yMin) continue;
      const z = y0 * sa + pz[i] * ca;
      if (z < 0) continue;
      const sx = cx + x0 * R;
      if (sx < -4 || sx > w + 4) continue;
      const sy = cy - y * R;
      const limb = 1 - z;                      // 1 at the horizon
      const isLand = land[i];
      ctx.globalAlpha = (isLand ? 0.5 : 0.13) * (0.35 + limb * limb * 1.6);
      ctx.fillStyle = isLand ? P.land : P.sea;
      const s = isLand ? 1.7 : 1.1;
      ctx.fillRect(sx, sy, s, s * (0.45 + z * 0.55));   // squashed near the horizon
    }

    // Orbit and station
    const Ro = R * 1.045;
    ctx.globalAlpha = 0.22;
    ctx.strokeStyle = P.orbit;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 9]);
    ctx.beginPath(); ctx.arc(cx, cy, Ro, 0, 6.2832); ctx.stroke();
    ctx.setLineDash([]);

    const span = Math.asin(Math.min(1, (w * 0.5 + 80) / Ro));
    const phi = -span + ((t * 0.035) % 1) * span * 2;
    for (let k = 0; k < 26; k++) {             // trail
      const p = phi - k * 0.004;
      ctx.globalAlpha = 0.5 * (1 - k / 26);
      ctx.fillStyle = P.station.trail;
      ctx.fillRect(cx + Math.sin(p) * Ro, cy - Math.cos(p) * Ro, 2, 2);
    }
    const sx = cx + Math.sin(phi) * Ro, sy = cy - Math.cos(phi) * Ro;
    g = ctx.createRadialGradient(sx, sy, 0, sx, sy, 16);
    g.addColorStop(0, `rgba(${P.station.core},.95)`);
    g.addColorStop(0.25, `rgba(${P.station.glow},.45)`);
    g.addColorStop(1, `rgba(${P.station.glow},0)`);
    ctx.globalAlpha = 1;
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(sx, sy, 16, 0, 6.2832); ctx.fill();

    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 0.95;
    ctx.fillStyle = P.station.label;
    ctx.font = '500 12.5px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillText(label, sx + 14, sy - 10);
    ctx.globalAlpha = 1;
  });
}
