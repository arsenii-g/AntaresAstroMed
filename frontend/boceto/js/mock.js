// Datos de ejemplo para ver la página sin API ni placa.
// Las evaluaciones siguen contracts/assessment.example.json (contrato ③) y
// la telemetría contracts/telemetry.example.json (contrato ①).
// Los textos imitan los del motor, pero están escritos a mano: son de ejemplo.

// Nombre y rol no vienen del motor: los pone la API o la web.
export const CREW = [
  { crew_id: "F3786E09", name: "A. Vega", role: "Commander" },
  { crew_id: "A1B2C3D4", name: "B. Okoro", role: "Flight engineer" },
];

const sys = (cardiovascular, neuro, musculoskeletal, environment) => ({
  cardiovascular, neuro, musculoskeletal, environment,
});
const ok = { level: 0, reasons: [] };

// Tendencias de ejemplo (contrato ③). En cada una, projected_7d y
// crosses_threshold_in_days salen de la misma recta, como hace el motor.
const PUSHUPS_DOWN = { indicator: "pushup_reps", projected_7d: 14.4, crosses_threshold_in_days: 4, threshold: 16.2, threshold_level: 2, slope_per_day: -0.6 };
const SYSTOLIC_UP = { indicator: "systolic_mmhg", projected_7d: 142.7, crosses_threshold_in_days: 5.7, threshold: 140, threshold_level: 2, slope_per_day: 2.1 };
const MOOD_FLAT = { indicator: "mood", projected_7d: 3.6, crosses_threshold_in_days: null, threshold: null, threshold_level: null, slope_per_day: -0.05 };

// Cada tripulante pasa por estos estados, uno cada STEP_MS.
const SCRIPT = {
  F3786E09: [
    {
      hr: 68, temp: 36.6, activity: "moving", still: 0,
      a: { overall_level: 0, systems: sys(ok, ok, ok, ok), trends: [], recommendations: [], earth_summary: null },
    },
    {
      hr: 64, temp: 36.5, activity: "still", still: 45,
      a: {
        overall_level: 1,
        systems: sys(ok, { level: null, reasons: ["Mood: no data"] },
          { level: 1, reasons: ["Time without moving 45 s, above 30 s"] }, ok),
        trends: [PUSHUPS_DOWN],
        recommendations: ["Stand up and move for 2 minutes", "Complete today's check: mood is missing"],
        earth_summary: null,
      },
    },
    {
      hr: 96, temp: 36.8, activity: "moving", still: 0,
      a: {
        overall_level: 0, systems: sys(ok, ok, ok, ok),
        trends: [PUSHUPS_DOWN],
        recommendations: ["Push-up count is trending down: add one resistance session this week"],
        earth_summary: null,
      },
    },
  ],
  A1B2C3D4: [
    {
      hr: 118, temp: 36.9, activity: "still", still: 20,
      a: {
        overall_level: 1,
        systems: sys({ level: 1, reasons: ["Heart rate 118 bpm, above 100 bpm"] }, ok, ok,
          { level: 1, reasons: ["Cabin humidity 72%, above 60%"] }),
        trends: [SYSTOLIC_UP, MOOD_FLAT],
        recommendations: ["Seated rest for 10 minutes, then repeat the heart rate reading", "Check cabin humidity control"],
        earth_summary: null,
      },
    },
    {
      hr: 156, temp: 37.2, activity: "still", still: 60,
      a: {
        overall_level: 1,
        systems: sys({ level: 1, reasons: ["Heart rate 156 bpm, above 100 bpm (not sustained yet: 1 of 3 readings)"] }, ok, ok,
          { level: 1, reasons: ["Cabin humidity 72%, above 60%"] }),
        trends: [SYSTOLIC_UP, MOOD_FLAT],
        recommendations: ["Stay seated and keep the sensor still", "Check cabin humidity control"],
        earth_summary: null,
      },
    },
    {
      hr: 157, temp: 37.3, activity: "still", still: 75,
      a: {
        overall_level: 3,
        systems: sys({ level: 3, reasons: ["Heart rate 157 bpm, above 150 bpm (sustained over 3 readings)"] }, ok, ok,
          { level: 1, reasons: ["Cabin humidity 72%, above 60%"] }),
        trends: [SYSTOLIC_UP, MOOD_FLAT],
        recommendations: ["Stop all activity and lie down", "Contact the flight surgeon now", "Check cabin humidity control"],
        earth_summary: "CREW A1B2C3D4 — LEVEL 3\nCardiovascular: heart rate 157 bpm at rest, above 150 bpm, sustained over 3 readings.\nEnvironment: cabin humidity 72%.\nAction taken: crew member at rest. Requesting medical guidance.",
      },
    },
  ],
};

const STEP_MS = 7000;
const TICK_MS = 1000;

/** Emite mensajes con el sobre del WebSocket (contrato ④): { type, data }. */
export function subscribe(onMessage) {
  const t0 = Date.now();
  let step = -1;

  const tick = () => {
    const now = new Date();
    const next = Math.floor((Date.now() - t0) / STEP_MS) % 3;
    const changed = next !== step;
    step = next;

    for (const { crew_id } of CREW) {
      const s = SCRIPT[crew_id][step];
      onMessage({
        type: "telemetry",
        data: {
          device_id: "mock-01",
          ts: now.toISOString(),
          met_s: 18245 + Math.floor((Date.now() - t0) / 1000),
          crew_id,
          vitals: {
            heart_rate_bpm: s.hr + Math.round((Math.random() - 0.5) * 4),
            hr_quality: 0.85, resp_rate_bpm: null,
            body_temp_c: +(s.temp + (Math.random() - 0.5) * 0.1).toFixed(1),
          },
          motion: { activity: s.activity, still_for_s: s.still },
          cabin: { temp_c: 23.0, humidity_pct: crew_id === "A1B2C3D4" ? 72 : 45, dew_point_c: 10.4, heat_index_c: 23.0, condensation_risk: "low" },
          alerts: [],
        },
      });
      if (changed) onMessage({ type: "assessment", data: { crew_id, ts: now.toISOString(), ...s.a } });
    }
  };

  tick();
  const id = setInterval(tick, TICK_MS);
  return () => clearInterval(id);
}
