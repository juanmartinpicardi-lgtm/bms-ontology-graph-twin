// Procedural textures (canvas, no image files) and the PBR material set. Each floor gets its own clones so a floor
// can fade on its own when the building is peeled.
import * as THREE from "three";

function canvasTex(size, draw, repeat = 1, srgb = true) {
  const c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d"); draw(g, size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat); t.anisotropy = 8;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function noise(g, s, base, amp, n = 9000, sz = 2) {
  g.fillStyle = base; g.fillRect(0, 0, s, s);
  for (let i = 0; i < n; i++) {
    const v = (Math.random() - .5) * amp; g.fillStyle = v > 0 ? `rgba(255,255,255,${v})` : `rgba(0,0,0,${-v})`;
    g.fillRect(Math.random() * s, Math.random() * s, sz * Math.random() + .5, sz * Math.random() + .5);
  }
}
export const TEX = {
  concrete: canvasTex(512, (g, s) => { noise(g, s, "#9a9893", .16, 26000, 3);
    for (let i = 0; i < 40; i++) { g.fillStyle = `rgba(0,0,0,${Math.random() * .05})`; g.beginPath();
      g.arc(Math.random() * s, Math.random() * s, 10 + Math.random() * 60, 0, 7); g.fill(); } }, 1),
  carpet: canvasTex(256, (g, s) => noise(g, s, "#5a6470", .22, 30000, 1.4), 1),
  roof: canvasTex(512, (g, s) => { noise(g, s, "#c9cbcc", .08, 12000, 3);
    g.strokeStyle = "rgba(0,0,0,.10)"; g.lineWidth = 2; for (let x = 0; x < s; x += 64) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, s); g.stroke(); } }, 1),
  brushed: canvasTex(256, (g, s) => { g.fillStyle = "#808080"; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 1400; i++) { g.fillStyle = `rgba(${Math.random() > .5 ? "255,255,255" : "0,0,0"},${Math.random() * .12})`;
      g.fillRect(0, Math.random() * s, s, Math.random() * 1.5); } }, 1, false),
  louver: canvasTex(128, (g, s) => { g.fillStyle = "#222"; g.fillRect(0, 0, s, s);
    for (let y = 0; y < s; y += 16) { const gr = g.createLinearGradient(0, y, 0, y + 16); gr.addColorStop(0, "#ddd"); gr.addColorStop(.7, "#777"); gr.addColorStop(1, "#111");
      g.fillStyle = gr; g.fillRect(0, y, s, 13); } }, 1, false),
  wood: canvasTex(256, (g, s) => { g.fillStyle = "#a07850"; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 160; i++) { g.strokeStyle = `rgba(60,35,15,${Math.random() * .25})`; g.lineWidth = Math.random() * 2;
      g.beginPath(); const y = Math.random() * s; g.moveTo(0, y); g.bezierCurveTo(s * .3, y + 6, s * .6, y - 6, s, y + 3); g.stroke(); } }, 1),
  tile: canvasTex(256, (g, s) => { noise(g, s, "#b8b6b0", .06, 6000, 2); g.strokeStyle = "rgba(0,0,0,.18)"; g.lineWidth = 2;
    for (let x = 0; x <= s; x += 64) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, s); g.stroke(); g.beginPath(); g.moveTo(0, x); g.lineTo(s, x); g.stroke(); } }, 1),
};

// A flow texture for animated relationship tubes: bright dashes that scroll along the tube.
export const flowTex = canvasTex(128, (g, s) => {
  const gr = g.createLinearGradient(0, 0, s, 0);
  gr.addColorStop(0, "rgba(255,255,255,.15)"); gr.addColorStop(.55, "rgba(255,255,255,.25)"); gr.addColorStop(.8, "rgba(255,255,255,1)"); gr.addColorStop(1, "rgba(255,255,255,.15)");
  g.fillStyle = gr; g.fillRect(0, 0, s, s);
}, 1, false);

const std = (o) => new THREE.MeshStandardMaterial(o);
const phys = (o) => new THREE.MeshPhysicalMaterial(o);
// Base palette; floors clone what they use through matsFor().
export function baseMaterials() {
  // Geometry UVs are in world tiles (boxGeo), so textures repeat once per tile; r is kept as a per-material tweak.
  const tex = (t, r) => { const c = t.clone(); c.needsUpdate = true; c.repeat.set(1, 1); return c; };
  return {
    concrete: std({ color: 0xb9b6ae, map: tex(TEX.concrete, .08), roughness: .92 }),
    slab: std({ color: 0x8f8d88, map: tex(TEX.concrete, .06), roughness: .95 }),
    slabEdge: std({ color: 0xd9d8d3, roughness: .7 }),
    carpet: std({ color: 0xffffff, map: tex(TEX.carpet, .35), roughness: 1 }),
    plantFloor: std({ color: 0x9c9a92, map: tex(TEX.concrete, .12), roughness: .8, metalness: 0 }),
    epoxy: std({ color: 0x6f7a78, roughness: .35, metalness: .05 }),
    roof: std({ color: 0xffffff, map: tex(TEX.roof, .05), roughness: .85 }),
    partition: std({ color: 0xeceae6, roughness: .85 }),
    glassPartition: phys({ color: 0xcfe6ee, roughness: .05, transparent: true, opacity: .18, metalness: 0, envMapIntensity: 1.2 }),
    curtain: phys({ color: 0x4f6f86, roughness: .03, metalness: .55, transparent: true, opacity: .58, envMapIntensity: 2.6, clearcoat: 1, clearcoatRoughness: .03,
      specularIntensity: 1, ior: 1.52 }),
    spandrel: phys({ color: 0x18232b, roughness: .12, metalness: .7, envMapIntensity: 2.0, clearcoat: 1 }),
    mullion: std({ color: 0xb8bcc0, roughness: .35, metalness: .85 }),
    darkMetal: std({ color: 0x3a3f45, roughness: .45, metalness: .7 }),
    casing: std({ color: 0xd6d8d6, roughness: .45, metalness: .55, roughnessMap: TEX.brushed }),
    casingBlue: std({ color: 0x5f7f9c, roughness: .4, metalness: .45, roughnessMap: TEX.brushed }),
    casingGreen: std({ color: 0x6e8b74, roughness: .45, metalness: .4, roughnessMap: TEX.brushed }),
    casingRed: std({ color: 0xa8433a, roughness: .42, metalness: .35 }),
    insulation: std({ color: 0xe8e6df, roughness: .65, metalness: .25 }),
    steel: std({ color: 0x9aa1a8, roughness: .3, metalness: .9 }),
    black: std({ color: 0x18191b, roughness: .6, metalness: .3 }),
    yellow: std({ color: 0xe0b23a, roughness: .5, metalness: .2 }),
    louver: std({ color: 0xc8cccf, map: TEX.louver, roughness: .5, metalness: .5 }),
    pipeCHW: std({ color: 0x3f7fc4, roughness: .35, metalness: .3 }),
    pipeHW: std({ color: 0xc4513f, roughness: .35, metalness: .3 }),
    pipeCW: std({ color: 0x3fa89a, roughness: .35, metalness: .3 }),
    duct: std({ color: 0xc7ccd0, roughness: .3, metalness: .85, roughnessMap: TEX.brushed }),
    desk: std({ color: 0xf2f0ea, roughness: .55 }),
    deskWood: std({ color: 0xffffff, map: tex(TEX.wood, 1), roughness: .6 }),
    chair: std({ color: 0x2b2e33, roughness: .7 }),
    monitor: std({ color: 0x111214, roughness: .25, metalness: .4, emissive: 0x0b1a2a, emissiveIntensity: .6 }),
    plant: std({ color: 0x3e7a3a, roughness: .9 }),
    pot: std({ color: 0xd8d2c4, roughness: .8 }),
    light: std({ color: 0xffffff, emissive: 0xfff3dc, emissiveIntensity: .0, roughness: .9 }),
    screen: std({ color: 0x0c1116, emissive: 0x2aa3ff, emissiveIntensity: .8, roughness: .3 }),
    led: std({ color: 0x0, emissive: 0x3fff8f, emissiveIntensity: 3 }),
    zone: std({ color: 0x3fb27f, roughness: .6, transparent: true, opacity: .95 }),
    volume: std({ color: 0x3fb27f, roughness: .2, transparent: true, opacity: .2, depthWrite: false }),
    lobby: std({ color: 0xffffff, map: tex(TEX.tile, .25), roughness: .3 }),
  };
}
export function matsFor(base) {
  const out = {};
  for (const [k, m] of Object.entries(base)) { out[k] = m.clone(); out[k].userData.baseOpacity = m.opacity; out[k].userData.baseTransparent = m.transparent; }
  return out;
}
