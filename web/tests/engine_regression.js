// node tests/engine_regression.js  -- v1 regression (scores, mic 1, SRP azimuths), 5 speakers + 16 mics, clamp, damping, zenith + dual-ring SRP
// v1 engine = web/src/engine.js from accio-sunshine/robot_acoustics @ e655ff9 (the published v1 page), vendored as a fixture
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..", "..");
const v1 = require("./fixtures/engine_v1.js"), v2 = require("../src/engine.js");
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
  // SRP: v1's peaks must come back with the same azimuths (v2 may add filler peaks so there is one per speaker); planar ring -> el null
  const pkOk = a.srp.peaks.every(az => b.srp.peaks.some(q => q.az === az)) && b.srp.peaks.every(q => q.el === null);
  ok(worst < 0.05 && md < 1e-3 && pkOk, `v1 regression '${name}': max score diff ${worst.toExponential(2)} dB, mic1 max abs diff ${md.toExponential(2)}, keys ${Object.keys(b.scores).length}, SRP v1 ${JSON.stringify(a.srp.peaks)} v2 ${JSON.stringify(b.srp.peaks.map(q => q.az))}, ${a.ms}ms vs ${b.ms}ms`);
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
  // band-limit with the engine FFT (>3 kHz or <1 kHz), then 20 dB Schroeder decay time from T0 = 1200 samples (75 ms, after the
  // 3-bounce images). Starting later (0.15 s) measured the numerical floor: at d=0.8 the HF tail is already >20 dB down by then.
  const decay = (h, hf) => {
    const n = h.length, re = Float64Array.from(h, (v, i) => i < 1200 ? 0 : v), im = new Float64Array(n), F = v2._test.fft; F(re, im, false);
    for (let k = 0; k < n; k++) { const f = Math.min(k, n - k) * v2.FS / n, keep = hf ? f > 3000 : f < 1000; if (!keep) { re[k] = 0; im[k] = 0; } }
    F(re, im, true);
    let e = 0; const cum = new Float64Array(n); for (let i = n - 1; i >= 0; i--) { e += re[i] * re[i]; cum[i] = e; }
    const t0 = cum[1200]; let i = 1200; while (i < n && cum[i] > t0 * 1e-2) i++; return (i - 1200) / v2.FS; };
  const h0 = rirs(0), h8 = rirs(0.8), hf0 = decay(h0, true), hf8 = decay(h8, true), lf0 = decay(h0, false), lf8 = decay(h8, false);
  ok(hf8 < hf0 * 0.8 && Math.abs(lf8 - lf0) < 0.1 * lf0, `damping: HF 20 dB decay ${hf0.toFixed(3)} s (d=0) -> ${hf8.toFixed(3)} s (d=0.8); LF ${lf0.toFixed(3)} -> ${lf8.toFixed(3)} s`);
  const z = v2.render({ ...DEF, ...OFF, babyOn: false, speakers: [sp("s1", "male", 0, 90, 1.5, 0, 0.3), sp("s2", "female", 90, 0, 1.5, 0, 2.6)] }, voices);
  ok(fin(z) && z.srp.peaks.length === 2 && z.srp.peaks.every(q => Number.isFinite(q.az) && q.el === null), "zenith speaker with ring: SRP ok, peaks " + JSON.stringify(z.srp.peaks));
  // dual ring (8 cm gap) resolves elevation: one talker 30 deg up, one 20 deg down
  const dr = v2.render({ ...DEF, ...OFF, babyOn: false, arrayShape: "dual_ring", ringGap: 8, speakers: [sp("s1", "male", 40, 30, 1.5, 0, 0.3), sp("s2", "female", 150, -20, 1.5, 0, 2.6)] }, voices);
  const near = (q, az, el) => Math.min(Math.abs(q.az - az), 360 - Math.abs(q.az - az)) <= 15 && Math.abs(q.el - el) <= 15;
  ok(fin(dr) && dr.srp.peaks.some(q => near(q, 40, 30)) && dr.srp.peaks.some(q => near(q, 150, -20)), "dual ring elevation (truth 40/30, 150/-20): peaks " + JSON.stringify(dr.srp.peaks));
}
{ // small rooms are not enlarged: the Automobile cabin is 2.7 x 1.6 x 1.2 m (the engine used to clamp W and H to >= 2 m)
  const n = v2.normalizeParams({ roomL: 2.7, roomW: 1.6, roomH: 1.2, arrayX: 2.0, arrayY: 0.8, arrayH: 0.8 });
  ok(n.roomL === 2.7 && n.roomW === 1.6 && n.roomH === 1.2 && n._warnings.length === 0, `car cabin kept at ${n.roomL} x ${n.roomW} x ${n.roomH} m`);
}
{ // dual-ring layout: mics 1..M/2 lower ring at i*360/(M/2), mics M/2+1..M upper ring offset half a step; same as the page's micAngles()
  const tpl = fs.readFileSync(path.join(__dirname, "..", "src", "robot_acoustic.template.html"), "utf8");
  const micAngles = new Function("return " + tpl.match(/function micAngles\(n, shape\) \{[\s\S]*?\n\}/)[0])();
  let bad = [];
  for (const M of [4, 6, 8, 12, 16]) for (const shape of ["ring", "dual_ring"]) {
    const pos = v2._test.engMicPositions({ radius: 5, micCount: M, arrayShape: shape, ringGap: 8 }, [0, 0, 0]), ui = micAngles(M, shape);
    pos.forEach((q, i) => {
      const az = (Math.atan2(q[1], q[0]) * 180 / Math.PI + 360) % 360, upper = shape === "dual_ring" && i >= M / 2;
      const zOk = shape === "ring" ? q[2] === 0 : (upper ? q[2] > 0 : q[2] < 0);
      if (Math.abs(((az - ui[i]) % 360 + 540) % 360 - 180) > 1e-6 || !zOk) bad.push(`${shape} M=${M} mic${i + 1}: engine ${az.toFixed(1)}/${q[2]}, page ${ui[i]}`);
    });
  }
  ok(bad.length === 0, "mic layout engine == page (ring + dual ring, 4-16 mics)" + (bad.length ? ": " + bad.slice(0, 4).join("; ") : ""));
  const r = v2.render({ ...DEF, ...OFF, babyOn: false, arrayShape: "dual_ring", ringGap: 8 }, voices);
  ok(Array.isArray(r.micPositions) && r.micPositions.length === 8 && r.micPositions[0][2] === -0.04 && r.micPositions[4][2] === 0.04,
    "render() returns micPositions for settings.json: " + JSON.stringify(r.micPositions.slice(0, 2)) + " ...");
}
process.exit(fail ? 1 : 0);
