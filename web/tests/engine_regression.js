// node tests/engine_regression.js  -- v1 regression, 5 speakers + 16 mics, clamp, damping, zenith SRP
const fs = require("fs"), os = require("os"), path = require("path"), cp = require("child_process");
const root = path.join(__dirname, "..", "..");
const tmp = path.join(os.tmpdir(), "engine_v1_head.js");
fs.writeFileSync(tmp, cp.execSync("git show HEAD:web/src/engine.js", { cwd: path.join(root, "web") }));
const v1 = require(tmp), v2 = require("../src/engine.js");
const ab = f => { const b = fs.readFileSync(path.join(root, "voices", f)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
const voices = { male: v2.readWav(ab("male.wav"), true).x, female: v2.readWav(ab("female.wav"), true).x, baby: v2.readWav(ab("baby.wav"), false).x };
globalThis.NOISE_GEN = { hum: (rng) => { const o = new Float64Array(v2.N); for (let i = 0; i < o.length; i++) o[i] = rng.g(); return o; } };
let fail = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fail++; };
const DEF = { rt60: 0.5, radius: 5, roomDb: 25, manAng: 40, womanAng: 150, dist: 1.5, babyOn: true, babyAng: 250, babyDist: 2.5, babyDb: -6,
  fanOn: true, fanDb: -6, fanRpm: 4200, neckOn: true, neckDb: -4, shouldersOn: true, shouldersDb: -8, footstepsOn: false, footstepsDb: -2, clicksOn: true, clicksDb: -10, humOn: true, humDb: -25 };
const OFF = { fanOn: false, neckOn: false, shouldersOn: false, footstepsOn: false, clicksOn: false, humOn: false };
const presets = { baby: OFF, fan: { ...OFF, fanOn: true, humOn: true }, robot: {}, quiet: { ...OFF, babyOn: false } };
const only = process.argv[2];
for (const [name, set] of Object.entries(presets)) {
  if (only && only !== name) continue;
  const p = { ...DEF, ...set }, a = v1.render(p, voices), b = v2.render(p, voices);
  let worst = 0; const map = { mic_man: "mic_s1", mic_woman: "mic_s2" };
  for (const k of Object.keys(a.scores)) {
    const k2 = map[k] || (k.startsWith("woman_") ? "s2_" + k.slice(6) : "s1_" + k.slice(4));
    worst = Math.max(worst, Math.abs(a.scores[k] - b.scores[k2]));
  }
  let md = 0; for (let i = 0; i < a.mics[0].length; i++) md = Math.max(md, Math.abs(a.mics[0][i] - b.mics[0][i]));
  ok(worst < 0.05 && md < 1e-3, `v1 regression '${name}': max score diff ${worst.toExponential(2)} dB, mic1 max abs diff ${md.toExponential(2)}, keys ${Object.keys(b.scores).length}, ${a.ms}ms vs ${b.ms}ms`);
}
if (!only) {
  const fin = r => [...r.mics, ...Object.values(r.tracks), ...Object.values(r.solos)].every(a => a.every(Number.isFinite)) && Object.values(r.scores).every(Number.isFinite);
  const sp = (id, voice, az, el, dist, db, start) => ({ id, voice, az, el, dist, db, start, target: id !== "s5" });
  const big = { ...DEF, rt60: 1.5, micCount: 16, speakers: [sp("s1", "male", 20, 0, 1.5, 0, 0.3), sp("s2", "female", 100, 30, 2, 0, 2.6), sp("s3", "male_low", 200, -20, 2, -3, 1), sp("s4", "female_high", 280, 50, 1.5, -3, 3), sp("s5", "baby", 330, 10, 3, -6, 0)],
    noises: [{ id: "n1", gen: "hum", az: 60, el: 20, dist: 3, db: -6, path: { az1: 200, el1: 40, dist1: 2 } }, { id: "n2", gen: "hum", az: 300, el: 0, dist: 4, db: -8 }] };
  const r = v2.render(big, voices);
  ok(fin(r) && r.ms <= 20000 && r.mics.length === 16, `5 speakers + 16 mics, rt60 1.5, 2 noises (1 moving): finite, ${r.ms} ms, ${Object.keys(r.scores).length} scores, peaks ${JSON.stringify(r.srp.peaks)}`);
  const c = v2.render({ ...DEF, ...OFF, speakers: [sp("s1", "male", 0, 0, 8, 0, 0.3), sp("s2", "female", 90, 0, 1.5, 0, 2.6)], roomL: 4, roomW: 4 }, voices);
  ok(c.warnings.length > 0 && c.sources[0].clamped, "source outside room clamped: " + c.warnings[0]);
  const rirs = d => v2._test.engRoomRirs([3.8, 2.5, 1.5], [[3.05, 2.5, 1.5]], [3, 2.5, 1.5], [6, 5, 3], 0.8, d, 32768, v2 && (() => { let s = 5; return { u: () => (s = (s * 16807) % 2147483647) / 2147483647, g() { let x = 0; for (let i = 0; i < 12; i++) x += this.u(); return x - 6; } }; })())[0];
  const decay = (h, hf) => { // band-limit with the engine FFT (>3 kHz or <1 kHz), then 20 dB Schroeder decay time after the early part
    const n = h.length, re = Float64Array.from(h, (v, i) => i < 2400 ? 0 : v), im = new Float64Array(n), F = v2._test.fft; F(re, im, false);
    for (let k = 0; k < n; k++) { const f = Math.min(k, n - k) * v2.FS / n, keep = hf ? f > 3000 : f < 1000; if (!keep) { re[k] = 0; im[k] = 0; } }
    F(re, im, true);
    let e = 0; const cum = new Float64Array(n); for (let i = n - 1; i >= 0; i--) { e += re[i] * re[i]; cum[i] = e; }
    const t0 = cum[2400]; let i = 2400; while (i < n && cum[i] > t0 * 1e-2) i++; return (i - 2400) / v2.FS; };
  const h0 = rirs(0), h8 = rirs(0.8), hf0 = decay(h0, true), hf8 = decay(h8, true), lf0 = decay(h0, false), lf8 = decay(h8, false);
  ok(hf8 < hf0 * 0.8, `damping: HF 20 dB decay ${hf0.toFixed(3)} s (d=0) -> ${hf8.toFixed(3)} s (d=0.8); LF ${lf0.toFixed(3)} -> ${lf8.toFixed(3)} s`);
  const z = v2.render({ ...DEF, ...OFF, babyOn: false, speakers: [sp("s1", "male", 0, 90, 1.5, 0, 0.3), sp("s2", "female", 90, 0, 1.5, 0, 2.6)] }, voices);
  ok(fin(z) && z.srp.peaks.length === 2 && z.srp.peaks.every(q => Number.isFinite(q.az) && Number.isFinite(q.el)), "zenith speaker with ring: SRP ok, peaks " + JSON.stringify(z.srp.peaks));
}
process.exit(fail ? 1 : 0);
