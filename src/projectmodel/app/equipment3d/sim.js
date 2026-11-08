// Simulated values (spec-equipment-3d §6.2). A sped-up day (1 real minute = 1 simulated hour) with an occupancy
// schedule and a sinusoidal outdoor temperature drives one load signal per AHU; a VAV derives its own load from its
// AHU's, so a building "breathes" together across pages. Everything is a pure function of (seed, scenario, hour):
// the same seed gives the same demo. Point specs (driver, unit, range) come from value_model.py in the payload.
const Sim = (() => {
  // FNV-1a string hash and an integer hash -> [0, 1)
  const hash = s => { let h = 0x811c9dc5; for (const c of String(s)) { h ^= c.codePointAt(0); h = Math.imul(h, 0x01000193); } return h >>> 0; };
  const rnd = (seed, i) => {
    let x = (seed ^ Math.imul(i | 0, 0x9e3779b1)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x21f0aaad); x = Math.imul(x ^ (x >>> 15), 0x735a2d97);
    return ((x ^ (x >>> 15)) >>> 0) / 4294967296;
  };
  // smooth value noise in [-1, 1]
  const noise = (seed, x) => {
    const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
    const a = rnd(seed, i) * 2 - 1, b = rnd(seed, i + 1) * 2 - 1;
    return a + (b - a) * u;
  };
  const clamp = (v, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));

  const SCENARIOS = {
    normal: { label: "Normal day", start: 9.5, dOAT: 0 },
    hot: { label: "Hot afternoon", start: 13.5, dOAT: 13 },
    stuck: { label: "Stuck reheat valve", start: 9.5, dOAT: 0, stuck: true, needs: "reheat" },
  };

  // The AHU's state at simulated hour h (hours since midnight of day 0).
  function ahuState(seed, sc, h) {
    const hod = ((h % 24) + 24) % 24;
    const oat = 66 + 14 * Math.sin(2 * Math.PI * (hod - 9) / 24) + sc.dOAT + 1.2 * noise(seed + 1, h * 2);
    const occ = hod >= 7 && hod < 19, run = occ;
    const load = run ? clamp(0.15 + (oat - 55) / 30 + 0.06 * noise(seed + 2, h * 1.5), 0.05, 1) : 0;
    const rat = run ? 71.5 + 2 * load + 0.3 * noise(seed + 3, h * 3) : 74 + 0.3 * noise(seed + 3, h);
    const oa = run ? (oat < rat ? clamp(20 + (68 - oat) * 4, 20, 100) : 20) : 0;
    const mat = run ? (oa / 100) * oat + (1 - oa / 100) * rat : rat;
    const cool = run && mat > 55.5 ? clamp((mat - 55) * 3.2 + load * 20) : 0;
    const heat = run && mat < 54.5 ? clamp((55 - mat) * 10) : 0;
    const sat = run ? 55 + 0.35 * noise(seed + 4, h * 6) + (cool >= 100 ? 1.5 : 0) : mat;
    const speed = run ? 40 + 55 * load : 0, rspeed = speed * 0.85;
    return {
      hod, occ, run, load, oat, rat, mat, sat, cool, heat, oa, ra: run ? 100 - oa : 100, relief: run ? clamp(oa - 15) : 0,
      fan: { supply: { run, speed, freq: speed * 0.6, power: 15 * (speed / 100) ** 3 },
             return: { run, speed: rspeed, freq: rspeed * 0.6, power: 7 * (rspeed / 100) ** 3 },
             exhaust: { run, speed: run ? 100 : 0 } },
      static: run ? 0.3 + 1.25 * (speed / 100) ** 2 : 0,
      building: run ? 0.03 + 0.01 * noise(seed + 5, h * 4) : 0,
      filterDp: run ? 0.05 + 0.55 * (speed / 100) ** 2 : 0,
      humidity: 45 + 6 * noise(seed + 6, h),
      oaFlow: run ? 12000 * (speed / 100) * (oa / 100) : 0,
    };
  }

  // A VAV's state: its own load follows its AHU's, with a per-box gain and offset; the stuck-valve scenario holds
  // the reheat valve at 100 % and lets the zone drift up.
  function vavState(seed, a, sc, h, elapsed, v) {
    const k = 0.75 + 0.5 * rnd(seed, 1), off = (rnd(seed, 2) - 0.5) * 0.3, design = 400 + Math.round(rnd(seed, 3) * 8) * 100;
    const run = a.run;
    const vload = run ? clamp(a.load * k + off + 0.08 * noise(seed + 7, h * 3), 0, 1) : 0;
    const damper = run ? clamp(30 + 70 * vload) : 0;
    let reheat = run && v.reheat && vload < 0.2 ? clamp((0.2 - vload) * 450) : 0;
    if (sc.stuck && v.reheat) reheat = 100;
    const zone = (run ? 73 + (vload - 0.5) * 1.5 : 76) + 0.25 * noise(seed + 8, h * 4) +
                 (sc.stuck && v.reheat ? Math.min(7, elapsed * 0.6) : 0);
    // dual duct: the cold deck carries the cooling, the hot deck makes up the minimum
    const cold = run ? clamp(15 + 85 * vload) : 0, hot = run ? clamp(55 - 70 * vload, 10, 100) : 0;
    const flowOf = d => design * d / 100 * (0.97 + 0.03 * noise(seed + 9, h * 5));
    return {
      run, vload, design, damper, reheat, zone,
      dat: run ? a.sat + reheat * 0.35 : zone - 1,
      airflow: flowOf(damper), airflowSp: design * (0.3 + 0.7 * vload),
      deck: { cold: { damper: cold, flow: flowOf(cold) * 0.8, sp: design * 0.8 * cold / 100 },
              hot: { damper: hot, flow: flowOf(hot) * 0.5, sp: design * 0.5 * hot / 100 } },
      fan: { terminal: { run, speed: run ? 100 : 0 } },
    };
  }

  // Per point: the driver's signal, plus a little sensor noise seeded by the point id.
  function pointValue(id, sp, s, h) {
    const a = s.ahu, v = s.vav, n = (scale) => scale * noise(hash(id), h * 4);
    const deck = sp.deck && v?.deck[sp.deck];
    const fan = (s.vav?.fan[sp.fan] || a.fan[sp.fan] || a.fan.supply);
    switch (sp.driver) {
      case "constant": return sp.base;
      case "outdoor_temp": return a.oat + n(0.1);
      case "return_temp": return a.rat + n(0.1);
      case "mixed_temp": return a.mat + n(0.15);
      case "supply_temp": return a.sat + n(0.1);
      case "zone_temp": return (v ? v.zone : a.rat) + n(0.05);
      case "discharge_temp": return (v ? v.dat : a.sat) + n(0.15);
      case "static_pressure": return a.static + n(0.02);
      case "building_pressure": return a.building;
      case "filter_dp": return a.filterDp;
      case "humidity": return a.humidity;
      case "cooling_valve": return a.cool;
      case "heating_valve": return a.heat;
      case "reheat_valve": return v ? v.reheat : a.heat;
      case "oa_damper": return a.oa;
      case "relief_damper": return a.relief;
      case "vav_damper": return deck ? deck.damper : v ? v.damper : a.oa;
      case "fan_speed": return fan.speed;
      case "fan_freq": return fan.freq ?? fan.speed * 0.6;
      case "fan_power": return (fan.power ?? 0) + (fan.run ? n(0.05) : 0);
      case "fan_run": return fan.run ? 1 : 0;
      case "airflow": return deck ? deck.flow : v ? v.airflow : a.oaFlow;
      case "airflow_sp": return deck ? deck.sp : v ? v.airflowSp : sp.base;
      case "oa_flow": return a.oaFlow;
      case "occupancy": return a.occ ? 1 : 0;
      case "filter_status": return 0;
      default: {  // generic: slow random walk around the spec's typical value
        const [lo, hi] = sp.range;
        return Math.min(hi, Math.max(lo, sp.base + (hi - lo) * 0.12 * noise(hash(id) + 11, h * 0.7)));
      }
    }
  }

  const DECIMALS = { "°F": 1, "inH₂O": 2, "Hz": 1, "kW": 1 };
  function format(sp, x) {
    if (sp.kind === "binary") {
      const t = sp.states[x ? 1 : 0];
      return { text: t, state: ["RUN", "ON", "OCC"].includes(t) ? "ok" : t === "DIRTY" ? "warn" : "off" };
    }
    const d = DECIMALS[sp.unit] ?? (sp.unit ? 0 : 1);
    return { text: sp.unit ? `${x.toFixed(d)} ${sp.unit}` : x.toFixed(d) };
  }

  // create(data, {seed, scenario}) -> {sample(h), hourAt(seconds), ...}. The default seed is the AHU's id, so a VAV
  // page and its AHU's page show the same day.
  function create(data, { seed = null, scenario = "normal", hour = null } = {}) {
    const eq = data.equipment, isVav = eq.template === "vav";
    const ahu = isVav ? (data.relations?.fed_by || []).find(r => r.template === "ahu") : eq;
    const aSeed = seed != null ? hash(`${seed}|${(ahu || eq).id}`) : hash((ahu || eq).id);
    const vSeed = seed != null ? hash(`${seed}|${eq.id}`) : hash(eq.id);
    let sc = SCENARIOS[scenario] || SCENARIOS.normal;
    const ids = Object.keys(data.points);
    function sample(h) {
      const elapsed = h - sc.start, a = ahuState(aSeed, sc, h);
      const s = { h, ahu: a, vav: isVav ? vavState(vSeed, a, sc, h, elapsed, data.variant || {}) : null };
      s.values = {};
      for (const id of ids) {
        const sp = data.points[id].sim;
        if (!sp) continue;
        const x = pointValue(id, sp, s, h);
        s.values[id] = { value: x, ...format(sp, x) };
      }
      return s;
    }
    return {
      sample,
      hourAt: seconds => (hour ?? sc.start) + seconds / 60,  // 1 real minute = 1 simulated hour
      scenario: () => scenario,
      setScenario: k => { scenario = SCENARIOS[k] ? k : "normal"; sc = SCENARIOS[scenario]; },
      scenarios: Object.entries(SCENARIOS).filter(([, s]) => !s.needs || (data.variant || {})[s.needs])
                       .map(([k, s]) => ({ key: k, label: s.label })),
    };
  }

  const clock = h => { const hod = ((h % 24) + 24) % 24, m = Math.floor((hod % 1) * 60); return `${String(Math.floor(hod)).padStart(2, "0")}:${String(m).padStart(2, "0")}`; };
  return { create, format, clock, hash, SCENARIOS };
})();
