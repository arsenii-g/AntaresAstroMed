// Demo mode for static hosting (GitHub Pages), where no API is running.
// It replays a real session recorded from the AstroMed API and the two-board
// simulator (demo/session.json): the same WebSocket messages and the same
// assessments the risk engine produced. Timestamps are moved to the present,
// and the recording loops. Daily checks are accepted but not evaluated.
//
// Active with ?demo in the URL, or when the page carries <meta name="astromed-demo">,
// which the published copy on the gh-pages branch carries (see frontend/web/README.md).
// Load this module before app.js: it replaces fetch and WebSocket for API calls.

const params = new URLSearchParams(location.search);
export const DEMO = params.has("demo") || (!params.has("api") && !!document.querySelector('meta[name="astromed-demo"]'));

const START_S = 100;  // start late enough that the charts already have history
const ISO = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g;

if (DEMO) {
  const session = fetch(new URL("../demo/session.json", import.meta.url)).then((r) => r.json());
  const pageStart = Date.now();
  const realFetch = window.fetch.bind(window);

  // Position in the recording, and the shift that maps recorded times to now.
  const clock = (s) => {
    const loop = s.duration_s - START_S;
    const elapsed = (Date.now() - pageStart) / 1000;
    const k = Math.floor(elapsed / loop);
    const pos = START_S + (elapsed - k * loop);
    const shiftMs = pageStart + k * loop * 1000 - START_S * 1000 - Date.parse(s.recorded_at);
    return { pos, shiftMs, loop: k };
  };
  const shift = (value, ms) => {
    if (typeof value === "string") return value.replace(ISO, (t) => new Date(Date.parse(t) + ms).toISOString());
    if (Array.isArray(value)) return value.map((v) => shift(v, ms));
    if (value && typeof value === "object") {
      const out = {};
      for (const [k, v] of Object.entries(value)) out[k] = shift(v, ms);
      return out;
    }
    return value;
  };
  const upTo = (s, pos) => s.ws.filter(([t]) => t <= pos).map(([, m]) => m);
  const last = (list, pred) => { for (let i = list.length - 1; i >= 0; i--) if (pred(list[i])) return list[i]; return null; };
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  async function api(url, init) {
    const s = await session;
    const { pos, shiftMs } = clock(s);
    const seen = upTo(s, pos);
    const crewId = url.searchParams.get("crew_id");
    const path = url.pathname.replace(/^.*\/api\/v1/, "");
    let m;
    if (path === "/checks" && init?.method === "POST") return json({ ok: true, duplicate: false, demo: true });
    if (path === "/crew") return json(s.crew);
    if (path === "/crew/active") {
      const checkin = last(seen, (x) => x.type === "event" && x.data.type === "crew_checkin");
      return json(shift(checkin ? { crew_id: checkin.data.data?.action === "in" ? checkin.data.crew_id : null, ts: checkin.data.ts }
                                : { crew_id: null, ts: null }, shiftMs));
    }
    if (path === "/events") {
      const events = seen.filter((x) => x.type === "event" && (!crewId || x.data.crew_id === crewId)).map((x) => x.data);
      return json(shift(events, shiftMs));
    }
    if ((m = path.match(/^\/crew\/([^/]+)\/telemetry$/))) {
      const id = decodeURIComponent(m[1]);
      const limit = Number(url.searchParams.get("limit")) || 48;
      return json(shift(seen.filter((x) => x.type === "telemetry" && x.data.crew_id === id).map((x) => x.data).slice(-limit), shiftMs));
    }
    if ((m = path.match(/^\/crew\/([^/]+)\/latest$/))) {
      const id = decodeURIComponent(m[1]);
      const info = s.crew.find((c) => c.crew_id === id);
      if (!info) return json({ detail: "Not found" }, 404);
      const of = (type, extra = () => true) => last(seen, (x) => x.type === type && x.data.crew_id === id && extra(x))?.data ?? null;
      return json(shift({
        crew_id: id, crew_name: info.name, crew_role: info.role, assigned: info.assigned,
        telemetry: of("telemetry"), assessment: of("assessment"),
        last_exercise: of("event", (x) => x.data.type === "exercise_summary"), assessment_error: null,
      }, shiftMs));
    }
    return json({ detail: "Not available in the demo" }, 404);
  }

  window.fetch = (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    return url.pathname.includes("/api/v1/") ? api(url, init) : realFetch(input, init);
  };

  // A WebSocket that plays the recorded messages at their recorded pace.
  class ReplaySocket {
    constructor() {
      this.readyState = 0;
      session.then((s) => {
        this.readyState = 1;
        this.onopen?.({});
        let { pos: prev, loop } = clock(s);
        this.timer = setInterval(() => {
          const now = clock(s);
          if (now.loop !== loop) { prev = START_S; loop = now.loop; }
          for (const [t, msg] of s.ws) {
            if (t > prev && t <= now.pos) this.onmessage?.({ data: JSON.stringify(shift(msg, now.shiftMs)) });
          }
          prev = now.pos;
        }, 250);
      });
    }
    send() {}
    close() { clearInterval(this.timer); this.readyState = 3; this.onclose?.({}); }
  }
  const RealWebSocket = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    return String(url).endsWith("/ws") ? new ReplaySocket() : new RealWebSocket(url, protocols);
  };

  // Say clearly that this is a recording.
  const banner = () => {
    const el = document.createElement("div");
    el.className = "demo-banner";
    el.setAttribute("role", "status");
    el.textContent = "Demo: replay of a session recorded from the AstroMed API and simulator. Daily checks are not saved.";
    document.body.prepend(el);
  };
  if (document.body) banner(); else document.addEventListener("DOMContentLoaded", banner);
}
