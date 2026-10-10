// Scenario tests. Run: node web/tests/scenarios_test.js  (from robot-audio) or node tests/scenarios_test.js (from web)
// Loads src/engine.js + src/scenarios.js as text into one vm context (like build.py concatenation).
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const root = path.join(__dirname, "..");
const code = fs.readFileSync(path.join(root, "src/engine.js"), "utf8") + "\n" + fs.readFileSync(path.join(root, "src/scenarios.js"), "utf8") +
  "\n;globalThis.__sc = { SCENARIOS, SCENARIO_ORDER, NOISE_GEN, FS, N, makeRng, readWav, fft };";
const ctx = { module: { exports: {} }, console, Math, Float64Array, Float32Array, Uint32Array };
vm.createContext(ctx); vm.runInContext(code, ctx, { filename: "engine+scenarios.js" });
const { SCENARIOS, SCENARIO_ORDER, NOISE_GEN, FS, N, makeRng, readWav, fft } = ctx.__sc;

let fail = 0;
const check = (ok, msg) => { if (!ok) { fail++; console.log("  FAIL: " + msg); } };

// voices: real files when present, else null (generators fall back to synthetic voice)
let voices = null;
try {
  const d = path.join(root, "..", "sim_conversation_out"), rd = (f, t) => { const b = fs.readFileSync(path.join(d, f)); return readWav(b.buffer.slice(b.byteOffset, b.byteOffset + b.length), t).x; };
  voices = { male: rd("clean_male.wav", true), female: rd("clean_female.wav", true), baby: rd("clean_baby.wav", false) };
  console.log("voices: real files (" + (voices.male.length / FS).toFixed(1) + " s male)");
} catch (e) { console.log("voices: NOT FOUND, using synthetic fallback (" + e.message + ")"); }

const rms = x => { let e = 0; for (const v of x) e += v * v; return Math.sqrt(e / x.length); };
function centroid(x) {
  const L = 1 << 17, re = new Float64Array(L), im = new Float64Array(L);
  re.set(x.subarray(0, Math.min(L, x.length))); fft(re, im, false);
  let a = 0, b = 0; for (let k = 1; k < L / 2; k++) { const m = re[k] * re[k] + im[k] * im[k]; a += m * k * FS / L; b += m; }
  return a / b;
}
function writeWav(file, x) {
  const n = x.length, buf = Buffer.alloc(44 + 2 * n);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + 2 * n, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(FS, 24); buf.writeUInt32LE(FS * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(2 * n, 40);
  for (let i = 0; i < n; i++) buf.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(x[i] * 32767))), 44 + 2 * i);
  fs.writeFileSync(file, buf);
}
const outDir = path.join(__dirname, "out"); fs.mkdirSync(outDir, { recursive: true });

check(JSON.stringify(SCENARIO_ORDER) === JSON.stringify(["home", "factory", "hospital", "automobile"]), "SCENARIO_ORDER");
const inRange = (v, lo, hi) => typeof v === "number" && isFinite(v) && v >= lo && v <= hi;
const R = 0.2;   // engine clamp margin: aim for sources that need no clamping

for (const id of SCENARIO_ORDER) {
  const S = SCENARIOS[id], P = S.params;
  console.log(`\n=== ${id}: ${S.label}`);
  check(S.label && S.desc, "label/desc");
  check(inRange(P.roomL, 2, 30) && inRange(P.roomW, 1.5, 30) && inRange(P.roomH, 1.0, 8) && inRange(P.rt60, 0.05, 1.5) && inRange(P.damping, 0, 1) && inRange(P.roomDb, 5, 40), "room ranges");
  
  check(inRange(P.arrayH, 0, P.roomH) && inRange(P.arrayX, 0, P.roomL) && inRange(P.arrayY, 0, P.roomW), "array inside room");
  check([4, 6, 8, 12, 16].includes(P.micCount) && inRange(P.radius, 3, 10), "mics");
  check(P.speakers.length >= 2 && P.speakers.length <= 5, "2-5 speakers");
  const ids = new Set();
  const pos = (s, az = s.az, el = s.el, dist = s.dist) => { const a = az * Math.PI / 180, e = el * Math.PI / 180; return [P.arrayX + dist * Math.cos(e) * Math.cos(a), P.arrayY + dist * Math.cos(e) * Math.sin(a), P.arrayH + dist * Math.sin(e)]; };
  const inside = (q, what) => check(q[0] >= R && q[0] <= P.roomL - R && q[1] >= R && q[1] <= P.roomW - R && q[2] >= R && q[2] <= P.roomH - R, `${what} outside room (margin ${R}): ${q.map(v => v.toFixed(2))}`);
  P.speakers.forEach((s, i) => {
    check(s.id === "s" + (i + 1), "speaker id " + s.id);
    check(["male", "female", "male_low", "female_high", "baby"].includes(s.voice), "voice " + s.voice);
    check(inRange(s.az, 0, 359) && inRange(s.el, -60, 90) && inRange(s.dist, 0.3, 8) && inRange(s.start, 0, 4.5), "speaker range " + s.id);
    check(typeof s.target === "boolean", "target bool");
    inside(pos(s), "speaker " + s.id);
  });
  check(P.speakers[0].db === 0, "s1 db = 0");
  check(P.noises.length >= 5 && P.noises.length <= 7, "5-7 noises, got " + P.noises.length);
  for (const n of P.noises) {
    check(!ids.has(n.id), "dup noise id " + n.id); ids.add(n.id);
    check(typeof NOISE_GEN[n.gen] === "function", "missing generator " + n.gen);
    check(inRange(n.az, 0, 359) && inRange(n.el, -60, 90) && inRange(n.dist, 0.3, 8) && typeof n.on === "boolean" && isFinite(n.db), "noise range " + n.id);
    inside(pos(n), "noise " + n.id);
    if (n.path) { check(inRange(n.path.az1, 0, 359) && inRange(n.path.el1, -60, 90) && inRange(n.path.dist1, 0.3, 8), "path range " + n.id); inside(pos(n, n.path.az1, n.path.el1, n.path.dist1), "path end " + n.id); }
  }
  if (id === "factory") {
    check(P.noises.filter(n => n.path).length >= 3, "factory: >=3 moving sources (AGV + 2 robots)");
    for (const g of ["machine_hum", "press", "airhiss", "agv_beeper", "robot_a", "robot_b", "conveyor"]) check(P.noises.some(n => n.gen === g), "factory has " + g);
  }

  // generators
  const t0 = Date.now(), sum = new Float64Array(N);
  console.log("  gen                  rms      centroid(Hz)  peak");
  for (const n of P.noises) {
    const g = NOISE_GEN[n.gen], a = g(makeRng(5), P, voices), b = g(makeRng(5), P, voices), c = g(makeRng(6), P, voices);
    check(a.length === N && a instanceof Float64Array, n.gen + " length/type");
    let finite = true, same = true, diff = false, pk = 0;
    for (let i = 0; i < N; i++) { if (!isFinite(a[i])) finite = false; if (a[i] !== b[i]) same = false; if (a[i] !== c[i]) diff = true; pk = Math.max(pk, Math.abs(a[i])); }
    check(finite, n.gen + " finite"); check(rms(a) > 0, n.gen + " rms>0"); check(same, n.gen + " deterministic"); check(diff, n.gen + " seed-dependent");
    console.log("  " + n.gen.padEnd(20) + rms(a).toFixed(3).padStart(7) + centroid(a).toFixed(0).padStart(12) + pk.toFixed(1).padStart(8));
    for (let i = 0; i < N; i++) sum[i] += a[i];
  }
  const ms = Date.now() - t0;   // includes the extra determinism/seed calls (3x), so real cost is ~1/3
  console.log(`  generation time incl. 3 calls/generator: ${ms} ms (about ${Math.round(ms / 3)} ms for one pass)`);
  let pk = 0; for (const v of sum) pk = Math.max(pk, Math.abs(v));
  for (let i = 0; i < N; i++) sum[i] *= 0.8 / pk;
  writeWav(path.join(outDir, id + "_ambience.wav"), sum);
}
// every NOISE_GEN is used by some scenario
const used = new Set(SCENARIO_ORDER.flatMap(i => SCENARIOS[i].params.noises.map(n => n.gen)));
for (const g of Object.keys(NOISE_GEN)) check(used.has(g), "unused generator " + g);
console.log(fail ? `\n${fail} FAILURES` : "\nALL PASSED"); process.exit(fail ? 1 : 0);
