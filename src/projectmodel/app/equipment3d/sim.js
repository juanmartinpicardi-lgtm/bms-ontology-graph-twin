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
    // Plant fault for the demo: chilled water supply drifts warm, so every AHU's cooling valve pins at 100 % and its
    // supply air climbs; VAVs open fully, can't reach their airflow setpoint, and zones warm up. The cause is upstream.
    chw_warm: { label: "Chilled water running warm", start: 13.5, dOAT: 6, chwWarm: true },
  };
  // How far the chilled-water fault has developed: already visible at the start, fully developed after ~50 s.
  const chwFault = (sc, h) => sc.chwWarm ? clamp(0.55 + (h - sc.start) * 0.55, 0, 1) : 0;
  const chwSupply = (sc, h) => 44 + 8.5 * chwFault(sc, h);  // °F; 44 is the design supply

  // Out of range: shown amber, the way an operator's graphic flags a value. Thresholds per driver.
  const WARN = {
    supply_temp: x => x > 57, chw_supply: x => x > 46.5,
    zone_temp: x => x > 76, cooling_valve: x => x >= 99, vav_damper: x => x >= 99,
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
    let cool = run && mat > 55.5 ? clamp((mat - 55) * 3.2 + load * 20) : 0;
    const heat = run && mat < 54.5 ? clamp((55 - mat) * 10) : 0;
    let sat = run ? 55 + 0.35 * noise(seed + 4, h * 6) + (cool >= 100 ? 1.5 : 0) : mat;
    // The coil can't cool the air below the chilled water plus its approach: with warm water the valve opens fully
    // and the supply air still runs warm.
    const floor = chwSupply(sc, h) + 6 + 2.5 * load;
    if (run && sc.chwWarm && floor > sat) { sat = Math.min(mat, floor + 0.3 * noise(seed + 4, h * 6)); cool = 100; }
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
    const vload0 = run ? clamp(a.load * k + off + 0.08 * noise(seed + 7, h * 3), 0, 1) : 0;
    const warm = sc.chwWarm && run ? Math.max(0, a.sat - 55) : 0;  // degrees the supply air is above design
    const vload = run ? clamp(vload0 + warm * 0.18, 0, 1) : 0;
    const damper = run ? clamp(30 + 70 * vload + warm * 4) : 0;
    let reheat = run && v.reheat && vload < 0.2 ? clamp((0.2 - vload) * 450) : 0;
    if (sc.stuck && v.reheat) reheat = 100;
    const zone = (run ? 73 + (vload - 0.5) * 1.5 : 76) + 0.25 * noise(seed + 8, h * 4) +
                 (sc.stuck && v.reheat ? Math.min(7, elapsed * 0.6) : 0) + warm * 0.75;
    // dual duct: the cold deck carries the cooling, the hot deck makes up the minimum
    const cold = run ? clamp(15 + 85 * vload) : 0, hot = run ? clamp(55 - 70 * vload, 10, 100) : 0;
    // with the AHU's fans already at full speed the duct can't deliver the design flow to every open box
    const flowOf = d => design * d / 100 * (0.97 + 0.03 * noise(seed + 9, h * 5)) * (warm > 1 ? 0.82 : 1);
    return {
      run, vload, design, damper, reheat, zone,
      dat: run ? a.sat + reheat * 0.35 : zone - 1,
      airflow: flowOf(damper), airflowSp: design * (0.3 + 0.7 * vload),
      deck: { cold: { damper: cold, flow: flowOf(cold) * 0.8, sp: design * 0.8 * cold / 100 },
              hot: { damper: hot, flow: flowOf(hot) * 0.5, sp: design * 0.5 * hot / 100 } },
      fan: { terminal: { run, speed: run ? 100 : 0 } },
    };
  }

  // A fan coil: like a VAV's zone, but its own valves do the work (a 2-pipe unit has only the coil it has).
  function fcuState(seed, a, sc, h, v) {
    const k = 0.75 + 0.5 * rnd(seed, 1), off = (rnd(seed, 2) - 0.5) * 0.3, run = a.run;
    const zload = run ? clamp(a.load * k + off + 0.08 * noise(seed + 7, h * 3), 0, 1) : 0;
    const short = v.cooling_coil && run ? chwFault(sc, h) : 0;  // warm chilled water: the coil can't keep up
    const cool = run && v.cooling_coil && (zload > 0.35 || short) ? clamp((zload - 0.35) * 160 + short * 100) : 0;
    const heat = run && v.heating_coil && zload < 0.15 && !short ? clamp((0.15 - zload) * 500) : 0;
    const zone = (run ? 73 + (zload - 0.5) * 1.5 : 76) + 0.25 * noise(seed + 8, h * 4) + short * 4;
    return { run, zload, cool, heat, zone, dat: run ? (cool ? 58 - cool * 0.04 : heat ? 78 + heat * 0.2 : zone - 0.5) : zone,
             fan: { terminal: { run, speed: run ? 100 : 0 } } };
  }

  // Plant: a site load (from the same outdoor day) staged across units by their number. CH-1 / B-1 lead, the next
  // starts as the load grows; pumps are duty/standby pairs (1 and A duty), the standby joins at high load.
  const rank = label => {
    const m = /(\d+)\s*([A-Za-z])?\s*$/.exec(label || "");
    return !m ? 0 : m[2] ? m[2].toUpperCase().charCodeAt(0) - 65 : Math.max(0, parseInt(m[1], 10) - 1);
  };
  function plantState(seed, a, sc, eq, v, h) {
    const k = rank(eq.label), hod = a.hod;
    const cool = a.run ? clamp(0.1 + a.load * 1.05 + chwFault(sc, h), 0.1, 1) : 0;
    const heat = a.run ? clamp(0.3 + (64 - a.oat) / 25, 0.15, 1) : hod >= 5 && hod < 7 ? 0.5 : 0;  // morning warm-up
    const n = (sd, f) => noise(seed + sd, h * f);
    if (eq.template === "chiller") {
      const on = Math.max(1, [0, 1, 2].filter(i => cool > i * 0.4).length), run = cool > k * 0.4;
      const plr = run ? clamp(cool / (0.4 * on), 0.2, 1) : 0;
      const chwS = run ? chwSupply(sc, h) + 0.25 * n(1, 4) + (plr >= 1 && !sc.chwWarm ? 1.5 : 0) : 56 + 0.4 * n(1, 1);
      const cwS = run ? clamp(70 + (a.oat - 66) * 0.45, 65, 88) + 0.3 * n(2, 3) : clamp(a.oat - 4, 55, 90);
      return { run, plr, load: cool, chwS, chwR: run ? chwS + 3 + 9 * plr : chwS + 0.3, cwS,
               cwR: run ? cwS + 2 + 8 * plr : cwS + 0.2, chwFlow: run ? 960 * (0.97 + 0.03 * n(3, 5)) : 0,
               cwFlow: run ? 1200 * (0.97 + 0.03 * n(4, 5)) : 0, power: run ? 40 + 260 * plr : 0 };
    }
    if (eq.template === "boiler") {
      const on = Math.max(1, [0, 1, 2].filter(i => heat > i * 0.35).length), run = heat > k * 0.35;
      const plr = run ? clamp(heat / (0.35 * on), 0.15, 1) : 0, firing = run ? clamp(20 + 80 * plr) : 0;
      const hwS = run ? 160 + 0.6 * n(1, 4) - (firing >= 100 ? 4 : 0) : 112 + 2 * n(1, 1);
      return { run, plr, load: heat, firing, hwS, hwR: run ? hwS - 8 - 14 * plr : hwS - 1, power: 0 };
    }
    // pump: what it moves sets which load it follows
    const load = v.medium === "hot_water" ? heat : cool, duty = k % 2 === 0;
    const run = duty ? load > 0 : load > 0.85;
    const speed = run ? clamp(45 + 50 * load + 2 * n(1, 3)) : 0;
    return { run, load, speed, freq: speed * 0.6, dp: run ? 4 + 14 * (speed / 100) ** 2 + 0.2 * n(2, 6) : 0,
             power: run ? 18 * (speed / 100) ** 3 : 0 };
  }

  // Per point: the driver's signal, plus a little sensor noise seeded by the point id.
  function pointValue(id, sp, s, h) {
    const a = s.ahu, v = s.vav || s.fcu, n = (scale) => scale * noise(hash(id), h * 4), pl = s.plant;
    const deck = sp.deck && s.vav?.deck[sp.deck];
    const fan = (v?.fan[sp.fan] || a.fan[sp.fan] || a.fan.supply);
    switch (sp.driver) {
      case "chw_supply": return pl ? pl.chwS + n(0.05) : 44;
      case "chw_return": return pl ? pl.chwR + n(0.05) : 54;
      case "cw_supply": return pl ? pl.cwS + n(0.05) : 80;
      case "cw_return": return pl ? pl.cwR + n(0.05) : 90;
      case "chw_flow": return pl?.chwFlow ?? 0;
      case "cw_flow": return pl?.cwFlow ?? 0;
      case "hw_supply": return pl ? pl.hwS + n(0.1) : 160;
      case "hw_return": return pl ? pl.hwR + n(0.1) : 140;
      case "firing_rate": return pl?.firing ?? 0;
      case "unit_run": return (pl || v || a).run ? 1 : 0;
      case "unit_power": return pl ? pl.power + (pl.run ? n(0.4) : 0) : 0;
      case "pump_speed": return pl?.speed ?? 0;
      case "pump_freq": return pl?.freq ?? 0;
      case "pump_dp": return pl?.dp ?? 0;
      case "cooling_valve": return s.fcu ? s.fcu.cool : a.cool;
      case "heating_valve": return s.fcu ? s.fcu.heat : a.heat;
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

  const DECIMALS = { "°F": 1, "inH₂O": 2, "Hz": 1, "kW": 1, "psi": 1 };
  function format(sp, x) {
    if (sp.kind === "binary") {
      const t = sp.states[x ? 1 : 0];
      return { text: t, state: ["RUN", "ON", "OCC", "OPEN"].includes(t) ? "ok" : t === "DIRTY" ? "warn" : "off" };
    }
    const d = DECIMALS[sp.unit] ?? (sp.unit ? 0 : 1);
    return { text: sp.unit ? `${x.toFixed(d)} ${sp.unit}` : x.toFixed(d) };
  }

  // create(data, {seed, scenario}) -> {sample(h), hourAt(seconds), ...}. The default seed is the AHU's id, so a VAV
  // page and its AHU's page show the same day; fan coils and plant follow one site-wide day per project, so units of
  // a plant stage together across their pages.
  // `offset` (seconds) continues a running demo across pages: the app passes how long the scenario has been running.
  function create(data, { seed = null, scenario = "normal", hour = null, offset = 0 } = {}) {
    const eq = data.equipment, t = eq.template, isVav = t === "vav", v = data.variant || {};
    const site = { id: `site|${data.project}` };
    const ahu = isVav ? (data.relations?.fed_by || []).find(r => r.template === "ahu") : t === "ahu" ? eq : site;
    const aSeed = seed != null ? hash(`${seed}|${(ahu || eq).id}`) : hash((ahu || eq).id);
    const vSeed = seed != null ? hash(`${seed}|${eq.id}`) : hash(eq.id);
    let sc = SCENARIOS[scenario] || SCENARIOS.normal;
    const ids = Object.keys(data.points);
    function sample(h) {
      const elapsed = h - sc.start, a = ahuState(aSeed, sc, h);
      const s = { h, ahu: a, vav: isVav ? vavState(vSeed, a, sc, h, elapsed, v) : null,
                  fcu: t === "fcu" ? fcuState(vSeed, a, sc, h, v) : null,
                  plant: ["chiller", "boiler", "pump"].includes(t) ? plantState(vSeed, a, sc, eq, v, h) : null };
      s.values = {};
      for (const id of ids) {
        const sp = data.points[id].sim;
        if (!sp) continue;
        const x = pointValue(id, sp, s, h);
        const f = format(sp, x);
        if (WARN[sp.driver]?.(x)) f.state = "warn";
        s.values[id] = { value: x, ...f };
      }
      return s;
    }
    return {
      sample,
      hourAt: seconds => (hour ?? sc.start) + (seconds + offset) / 60,  // 1 real minute = 1 simulated hour
      scenario: () => scenario,
      setScenario: k => { scenario = SCENARIOS[k] ? k : "normal"; sc = SCENARIOS[scenario]; },
      scenarios: Object.entries(SCENARIOS).filter(([, s]) => !s.needs || (data.variant || {})[s.needs])
                       .map(([k, s]) => ({ key: k, label: s.label })),
    };
  }

  const clock = h => { const hod = ((h % 24) + 24) % 24, m = Math.floor((hod % 1) * 60); return `${String(Math.floor(hod)).padStart(2, "0")}:${String(m).padStart(2, "0")}`; };
  return { create, format, clock, hash, SCENARIOS };
})();
