// node tools/export_scene.js <scene> <outdir> [--set '{"damping": 0}']
//   <scene> = home | factory | hospital | automobile (scenario defaults) or baby | fan | robot | quiet (Custom classic tests)
// Renders the scene with the page's engine and writes what the Python cross-check (python/score_scene.py) needs, in the
// same layout as the page's zip: settings.json, scene.json (resolved geometry), dry/<source>.wav (32-bit float), page_scores.json.
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const web = path.join(__dirname, ".."), root = path.join(web, "..");
const ctx = { console, Math, Date, Float64Array, Float32Array, Uint32Array, Array, Object, JSON, Number, String, Set };
vm.createContext(ctx);
vm.runInContext(["engine.js", "scenarios.js"].map(f => fs.readFileSync(path.join(web, "src", f), "utf8")).join("\n") +
  "\n;globalThis.__x = { render, readWav, SCENARIOS };", ctx);
const { render, readWav, SCENARIOS } = ctx.__x;

const DEF = { rt60: 0.5, radius: 5, roomDb: 25, manAng: 40, womanAng: 150, dist: 1.5, babyOn: true, babyAng: 250, babyDist: 2.5, babyDb: -6,
  fanOn: true, fanDb: -6, fanRpm: 4200, neckOn: true, neckDb: -4, shouldersOn: true, shouldersDb: -8, footstepsOn: false, footstepsDb: -2,
  clicksOn: true, clicksDb: -10, humOn: true, humDb: -25 };   // the page's classic-test defaults (template DEF / PRESETS)
const OFF = { fanOn: false, neckOn: false, shouldersOn: false, footstepsOn: false, clicksOn: false, humOn: false };
const PRESETS = { baby: OFF, fan: { ...OFF, fanOn: true, humOn: true }, robot: {}, quiet: { ...OFF, babyOn: false } };

function paramsFor(scene) {
  if (SCENARIOS[scene]) return JSON.parse(JSON.stringify(SCENARIOS[scene].params));
  if (PRESETS[scene]) return { ...DEF, ...PRESETS[scene], scenario: "custom" };
  throw new Error(`unknown scene '${scene}' (scenarios: ${Object.keys(SCENARIOS).join(", ")}; classic tests: ${Object.keys(PRESETS).join(", ")})`);
}
function wavF32(x, rate = 16000) {
  const n = x.length, b = Buffer.alloc(44 + 4 * n);
  b.write("RIFF", 0); b.writeUInt32LE(36 + 4 * n, 4); b.write("WAVE", 8); b.write("fmt ", 12); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(3, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate * 4, 28); b.writeUInt16LE(4, 32); b.writeUInt16LE(32, 34);
  b.write("data", 36); b.writeUInt32LE(4 * n, 40);
  for (let i = 0; i < n; i++) b.writeFloatLE(x[i], 44 + 4 * i);
  return b;
}
function main() {
  const [scene, out, flag, extra] = process.argv.slice(2);
  if (!scene || !out) { console.error("usage: node tools/export_scene.js <scene> <outdir>"); process.exit(2); }
  const ab = f => { const b = fs.readFileSync(path.join(root, "voices", f)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
  const voices = { male: readWav(ab("male.wav"), true).x, female: readWav(ab("female.wav"), true).x, baby: readWav(ab("baby.wav"), false).x };
  const p = { ...paramsFor(scene), ...(flag === "--set" ? JSON.parse(extra) : {}) }, res = render(p, voices);   // --set: override settings (for tests)
  fs.mkdirSync(path.join(out, "dry"), { recursive: true });
  fs.writeFileSync(path.join(out, "settings.json"), JSON.stringify({ ...p, schema: 2, micPositions: res.micPositions }, null, 2) + "\n");
  fs.writeFileSync(path.join(out, "scene.json"), JSON.stringify({ name: scene, ...res.geometry }, null, 1) + "\n");
  fs.writeFileSync(path.join(out, "page_scores.json"), JSON.stringify(res.scores, null, 1) + "\n");
  for (const [k, v] of Object.entries(res.dry)) fs.writeFileSync(path.join(out, "dry", k + ".wav"), wavF32(v));
  console.log(`${scene}: ${Object.keys(res.dry).length} dry sources, ${res.mics.length} mics, rendered in ${res.ms} ms -> ${out}`);
}
main();
