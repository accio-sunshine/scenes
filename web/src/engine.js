// Robot Acoustic audio engine. Runs in a Web Worker (or Node for testing).
// Mirrors sim_conversation.py + sim_8mic_robot_noise.py: same geometry, voices,
// robot noise recipes, levels and MPDR beamformer. The room is lighter than
// pyroomacoustics: exact image sources up to 3 bounces plus a diffuse late tail.
"use strict";
const FS = 16000, DUR = 5.5, N = Math.round(DUR * FS), C = 343, NFFT = 512, HOP = 128;

// ---------------------------------------------------------------- random numbers
function makeRng(seed) {
  let a = seed >>> 0;
  const u = () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  return { u, g() { let x = 0; while (x === 0) x = u(); return Math.sqrt(-2 * Math.log(x)) * Math.cos(2 * Math.PI * u()); } };
}

// ---------------------------------------------------------------- FFT (in place, radix 2)
const tables = {};
function fft(re, im, inverse) {
  const n = re.length;
  let T = tables[n];
  if (!T) {
    const cos = new Float64Array(n / 2), sin = new Float64Array(n / 2), rev = new Uint32Array(n);
    for (let i = 0; i < n / 2; i++) { cos[i] = Math.cos(2 * Math.PI * i / n); sin[i] = Math.sin(2 * Math.PI * i / n); }
    const bits = Math.log2(n);
    for (let i = 0; i < n; i++) { let r = 0; for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b); rev[i] = r; }
    T = tables[n] = { cos, sin, rev };
  }
  const { cos, sin, rev } = T;
  for (let i = 0; i < n; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
  const sg = inverse ? 1 : -1;
  for (let size = 2; size <= n; size <<= 1) {
    const half = size >> 1, step = n / size;
    for (let i = 0; i < n; i += size) {
      for (let j = 0, k = 0; j < half; j++, k += step) {
        const wr = cos[k], wi = sg * sin[k];
        const a = i + j, b = a + half;
        const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
      }
    }
  }
  if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
}
const nextPow2 = n => 1 << Math.ceil(Math.log2(n));

// ---------------------------------------------------------------- noise makers (sim_8mic_robot_noise.py)
function bandnoise(lo, hi, n, rng) {
  const L = nextPow2(n), re = new Float64Array(L), im = new Float64Array(L);
  for (let i = 0; i < n; i++) re[i] = rng.g();
  fft(re, im, false);
  for (let k = 0; k <= L / 2; k++) {
    const f = Math.max(k * FS / L, 1e-3);
    const h = 1 / Math.sqrt((1 + (lo / f) ** 8) * (1 + (f / hi) ** 8));
    re[k] *= h; im[k] *= h;
    if (k > 0 && k < L / 2) { re[L - k] *= h; im[L - k] *= h; }
  }
  fft(re, im, true);
  return re.slice(0, n);
}
function tone(freq, harmonics, rng) {
  const out = new Float64Array(N);
  const phs = harmonics.map(() => rng.u() * 2 * Math.PI);
  let ph = 0;
  for (let i = 0; i < N; i++) {
    ph += 2 * Math.PI * freq[i] / FS;
    let s = 0;
    harmonics.forEach(([k, a], j) => { s += a * Math.sin(k * ph + phs[j]); });
    out[i] = s;
  }
  return out;
}
function motorState(fanMax) {
  const fan = new Float64Array(N), neck = new Float64Array(N), sh = new Float64Array(N), walk = new Float64Array(N);
  const fanStart = 2400 * fanMax / 4200;
  for (let i = 0; i < N; i++) {
    const t = i / FS;
    fan[i] = t < 2 ? fanStart + (fanMax - fanStart) * t / 2 : fanMax;
    for (const [t0, t1, v] of [[0.8, 1.6, 1.2], [3.4, 4.0, -1.6]]) if (t >= t0 && t < t1) neck[i] = v * Math.sin(Math.PI * (t - t0) / (t1 - t0));
    if (t >= 1.8 && t < 2.8) sh[i] = 2.0 * Math.sin(2 * Math.PI * 1.5 * (t - 1.8));
    if (t >= 2.6 && t < 4.8) walk[i] = 1;
  }
  return { fan, neck, sh, walk };
}
function makeFan(ms, rng) {
  const bpf = ms.fan.map(r => r / 60 * 7);
  const hum = tone(bpf, [[1, 1.0], [2, 0.5], [3, 0.25], [4, 0.1]], rng);
  const air = bandnoise(100, 6000, N, rng);
  const out = new Float64Array(N);
  let rot = 0;
  for (let i = 0; i < N; i++) {
    rot += 2 * Math.PI * ms.fan[i] / 60 / FS;
    out[i] = (0.6 * hum[i] + air[i]) * (1 + 0.15 * Math.sin(rot)) * (ms.fan[i] / 4200);
  }
  return out;
}
function makeServo(vel, base, span, rng) {
  let mx = 1e-9; for (const v of vel) mx = Math.max(mx, Math.abs(v));
  const speed = vel.map(v => Math.abs(v) / mx);
  const whine = tone(speed.map(s => base + span * s), [[1, 1.0], [2, 0.6], [3, 0.3], [5, 0.15]], rng);
  const grind = bandnoise(1500, 6000, N, rng);
  return whine.map((w, i) => (w + 0.7 * grind[i] * (0.5 + 0.5 * Math.sin(2 * Math.PI * 37 * i / FS))) * speed[i]);
}
function makeFootsteps(ms, rng) {
  const out = new Float64Array(N);
  let first = -1, last = -1;
  for (let i = 0; i < N; i++) if (ms.walk[i]) { if (first < 0) first = i; last = i; }
  if (first < 0) return out;
  const K = Math.round(0.25 * FS);
  for (let s = first; s < last; s += Math.round(0.55 * FS)) {
    const click = bandnoise(2000, 7000, K, rng), amp = 0.8 + 0.4 * rng.u();
    for (let k = 0; k < K && s + k < N; k++) {
      const tk = k / FS;
      out[s + k] += (Math.sin(2 * Math.PI * 70 * tk) * Math.exp(-tk / 0.04) + 0.4 * click[k] * Math.exp(-tk / 0.004)) * amp;
    }
  }
  return out;
}
function makeClicks(ms, rng) {
  const out = new Float64Array(N), K = Math.round(0.02 * FS);
  const click = bandnoise(1000, 7000, K, rng).map((x, k) => x * Math.exp(-k / FS / 0.003));
  for (const v of [ms.neck, ms.sh]) {
    for (let i = 0; i < N - 1; i++) {
      if ((Math.abs(v[i]) > 1e-3) !== (Math.abs(v[i + 1]) > 1e-3)) for (let k = 0; k < K && i + k < N; k++) out[i + k] += click[k];
    }
  }
  return out;
}
function makeHum(rng) { return tone(new Float64Array(N).fill(50), [[1, 1.0], [2, 0.4], [3, 0.5], [5, 0.2]], rng); }

// ---------------------------------------------------------------- parameters (schema 2)
const engClamp = (x, a, b) => Math.min(b, Math.max(a, x));
const ENG_VOICE_IDS = ["male", "female", "male_low", "female_high", "baby"];
const ENG_ROBOT_DB_DEF = { fanDb: -6, neckDb: -4, shouldersDb: -8, footstepsDb: -2, clicksDb: -10, humDb: -25 };
const ROBOT_KEYS = ["fan", "neck", "shoulders", "footsteps", "clicks", "hum"];

// Map any parameter object (legacy v1 or schema 2) to a full schema-2 object. Never mutates its input.
// Out-of-range values are clamped; what was changed is listed in the returned object's _warnings.
function normalizeParams(p0) {
  const p = Object.assign({}, p0), warn = [];
  const num = (k, d, lo, hi) => {
    let v = p[k] == null || p[k] === "" ? NaN : Number(p[k]);
    if (!Number.isFinite(v)) v = d;
    if (lo !== undefined) v = engClamp(v, lo, hi);
    p[k] = v;
  };
  p.schema = 2;
  p.scenario = ["home", "factory", "hospital", "automobile", "custom"].includes(p.scenario) ? p.scenario : "custom";
  num("roomL", 6, 2, 30); num("roomW", 5, 2, 30); num("roomH", 3, 2, 8);
  num("rt60", 0.5, 0.05, 1.5); num("damping", 0, 0, 1); num("roomDb", 25); num("radius", 5, 1, 20);
  num("fanRpm", 4200, 600, 20000);
  for (const k of ROBOT_KEYS) { p[k + "On"] = !!p[k + "On"]; num(k + "Db", ENG_ROBOT_DB_DEF[k + "Db"]); }

  // microphones
  num("micCount", 8);
  let mc = Math.round(p.micCount);
  if (mc % 2) mc += 1;
  mc = engClamp(mc, 2, 16);
  if (mc !== p.micCount) warn.push("Mic count " + p.micCount + " changed to " + mc + " (even, 2-16).");
  p.micCount = mc;
  p.arrayShape = p.arrayShape === "dual_ring" ? "dual_ring" : "ring";
  num("ringGap", 8, 1, 30);
  // array centre: room centre, height H/2 limited to 1.2-1.5 m (v1: 1.5 m)
  num("arrayX", p.roomL / 2); num("arrayY", p.roomW / 2);
  let h0 = engClamp(p.roomH / 2, 1.2, 1.5); if (h0 > p.roomH - 0.25) h0 = p.roomH / 2;
  num("arrayH", h0);
  const r = p.radius / 100, hz = p.arrayShape === "dual_ring" ? p.ringGap / 200 : 0, mg = 0.2;
  const fit = (k, lo, hi, name) => {
    if (lo > hi) { lo = hi = (lo + hi) / 2; }
    const v = engClamp(p[k], lo, hi);
    if (Math.abs(v - p[k]) > 1e-9) warn.push("Array " + name + " moved to " + v.toFixed(2) + " m to keep the mics 0.2 m inside the room.");
    p[k] = v;
  };
  fit("arrayX", r + mg, p.roomL - r - mg, "x"); fit("arrayY", r + mg, p.roomW - r - mg, "y"); fit("arrayH", hz + mg, p.roomH - hz - mg, "height");

  // speakers
  p._legacy = !Array.isArray(p.speakers);
  if (!Array.isArray(p.speakers)) {
    num("manAng", 40); num("womanAng", 150); num("dist", 1.5); num("babyAng", 250); num("babyDist", 2.5); num("babyDb", -6);
    p.speakers = [
      { id: "s1", voice: "male", az: p.manAng, el: 0, dist: p.dist, db: 0, start: 0.3, target: true },
      { id: "s2", voice: "female", az: p.womanAng, el: 0, dist: p.dist, db: 0, start: 2.6, target: true },
    ];
    if (p.babyOn) {
      // v1 puts the baby 0.7 m below the ring plane at horizontal distance babyDist. The spec's el = asin(-0.7/babyDist)
      // with dist = babyDist would put it at horizontal sqrt(d^2-0.49), so use atan2 / hypot, which is exact.
      p.speakers.push({ id: "s3", voice: "baby", az: p.babyAng, el: Math.atan2(-0.7, p.babyDist) * 180 / Math.PI,
        dist: Math.hypot(p.babyDist, 0.7), db: p.babyDb, start: 0, target: false });
    }
  }
  const defVoice = ["male", "female", "male_low", "female_high", "baby"];
  p.speakers = p.speakers.slice(0, 5).map((s0, i) => {
    const s = Object.assign({ id: "s" + (i + 1), voice: defVoice[i], az: 0, el: 0, dist: 1.5, db: 0, start: 0, target: true }, s0);
    s.id = "s" + (i + 1);
    if (!ENG_VOICE_IDS.includes(s.voice)) { warn.push("Speaker " + (i + 1) + ": unknown voice '" + s.voice + "', using " + defVoice[i] + "."); s.voice = defVoice[i]; }
    s.az = ((Number(s.az) % 360) + 360) % 360 || 0; s.el = engClamp(Number(s.el) || 0, -60, 90);
    s.dist = engClamp(Number(s.dist) || 1.5, 0.3, 8); s.db = i === 0 ? 0 : (Number.isFinite(Number(s.db)) ? Number(s.db) : 0);
    s.start = engClamp(Number(s.start) || 0, 0, 4.5); s.target = s.target !== false;
    return s;
  });
  if (p0.speakers && p0.speakers.length > 5) warn.push("Only the first 5 speakers are used.");
  if (p.speakers.length === 0) p.speakers = [{ id: "s1", voice: "male", az: 40, el: 0, dist: 1.5, db: 0, start: 0.3, target: true }];

  // ambient noise sources
  const used = new Set(p.speakers.map(s => s.id).concat(ROBOT_KEYS, ["mic1"]));
  p.noises = (Array.isArray(p.noises) ? p.noises : []).map((n0, i) => {
    const n = Object.assign({ id: "n" + (i + 1), label: "", gen: "", az: 0, el: 0, dist: 3, db: -10, on: true, path: null }, n0);
    let id = String(n.id), q = 2; while (used.has(id)) id = n.id + "_" + q++;
    used.add(id); n.id = id; if (!n.label) n.label = id;
    n.az = ((Number(n.az) % 360) + 360) % 360 || 0; n.el = engClamp(Number(n.el) || 0, -60, 90); n.dist = engClamp(Number(n.dist) || 3, 0.2, 30);
    n.db = Number.isFinite(Number(n.db)) ? Number(n.db) : -10; n.on = n.on !== false;
    if (n.path) n.path = { az1: ((Number(n.path.az1) % 360) + 360) % 360 || 0, el1: engClamp(Number(n.path.el1) || 0, -60, 90), dist1: engClamp(Number(n.path.dist1) || n.dist, 0.2, 30) };
    else n.path = null;
    return n;
  });
  p._warnings = warn;
  return p;
}

// ---------------------------------------------------------------- geometry
// Position = centre + dist * (cos el cos az, cos el sin az, sin el); az counter-clockwise from the robot's front.
function engAim(cen, az, el, dist) {
  const a = az * Math.PI / 180, e = el * Math.PI / 180;
  return [cen[0] + dist * Math.cos(e) * Math.cos(a), cen[1] + dist * Math.cos(e) * Math.sin(a), cen[2] + dist * Math.sin(e)];
}
// Place a source, clamping it `margin` m inside the room. Returns final pos and az/el/dist as seen from the array centre.
function engPlace(cen, room, az, el, dist, margin) {
  const raw = engAim(cen, az, el, dist), pos = raw.map((v, i) => engClamp(v, margin, room[i] - margin));
  const clamped = pos.some((v, i) => Math.abs(v - raw[i]) > 1e-9);
  if (!clamped) return { pos, clamped, az, el, dist, raw };
  const dx = pos[0] - cen[0], dy = pos[1] - cen[1], dz = pos[2] - cen[2], d = Math.hypot(dx, dy, dz) || 1e-9;
  return { pos, clamped, az: ((Math.atan2(dy, dx) * 180 / Math.PI) + 360) % 360, el: Math.asin(engClamp(dz / d, -1, 1)) * 180 / Math.PI, dist: d, raw };
}
const dist3 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const ENG_ROBOT_REL = { fan: [180, 0.07, -0.03], neck: [0, 0, -0.10], shoulders: [90, 0.18, -0.30], footsteps: [0, 0.10, -1.40], clicks: [0, 0, -0.10] };
const ENG_ROBOT_LABEL = { fan: "Cooling fan", neck: "Neck servo", shoulders: "Shoulder servos", footsteps: "Footsteps", clicks: "Brake clicks", hum: "Electrical hum" };
function engRobotPlace(cen, room, k) {   // robot noises ride on the body, so they follow the array centre
  const [deg, d, dz] = ENG_ROBOT_REL[k], a = deg * Math.PI / 180;
  const raw = [cen[0] + d * Math.cos(a), cen[1] + d * Math.sin(a), cen[2] + dz];
  const pos = raw.map((v, i) => engClamp(v, 0.05, room[i] - 0.05));
  const clamped = pos.some((v, i) => Math.abs(v - raw[i]) > 1e-9);
  const dx = pos[0] - cen[0], dy = pos[1] - cen[1], dzz = pos[2] - cen[2], dd = Math.hypot(dx, dy, dzz) || 1e-9;
  return { pos, clamped, az: ((Math.atan2(dy, dx) * 180 / Math.PI) + 360) % 360, el: Math.asin(engClamp(dzz / dd, -1, 1)) * 180 / Math.PI, dist: dd };
}
// ring: M mics on a circle (v1 layout). dual_ring: M/2 on each of two rings ringGap cm apart in height, the upper one
// rotated by half a step. Returns absolute positions.
function engMicPositions(p, cen) {
  const r = p.radius / 100, M = p.micCount, out = [];
  if (p.arrayShape === "dual_ring") {
    const h = M / 2, gap = p.ringGap / 100;
    for (let ring = 0; ring < 2; ring++) for (let i = 0; i < h; i++) {
      const a = 2 * Math.PI * i / h + ring * Math.PI / h;
      out.push([cen[0] + r * Math.cos(a), cen[1] + r * Math.sin(a), cen[2] + (ring ? gap / 2 : -gap / 2)]);
    }
  } else for (let i = 0; i < M; i++) {
    const a = 2 * Math.PI * i / M;
    out.push([cen[0] + r * Math.cos(a), cen[1] + r * Math.sin(a), cen[2]]);
  }
  return out;
}

// ---------------------------------------------------------------- room impulse responses
// Image sources up to 3 bounces (exact) + a diffuse late tail. Damping d (0-1): wall absorption rises with frequency,
// so (a) early reflections lose amplitude (alpha_e = midway between the nominal and the HF Sabine alpha) and
// (b) the tail's high band decays with rt60Hf = rt60 * (1 - 0.75 d) and starts lower (HF Sabine level).
// d = 0 takes the v1 code path unchanged.
function engRt60Hf(rt60, damping) { return rt60 * (1 - 0.75 * damping); }
function engRoomRirs(src, mics, cen, room, rt60, damping, Lr, rng) {
  const V = room[0] * room[1] * room[2], S = 2 * (room[0] * room[1] + room[0] * room[2] + room[1] * room[2]);
  const alpha = Math.min(0.99, 0.161 * V / (S * rt60));
  const rt60Hf = engRt60Hf(rt60, damping), alphaH = Math.min(0.99, 0.161 * V / (S * rt60Hf));
  const beta = Math.sqrt(1 - (alpha + 0.5 * (alphaH - alpha)));
  const h = mics.map(() => new Float64Array(Lr));
  const K = 3, TAPS = 16;
  let early = 0;
  for (let nx = -K; nx <= K; nx++) for (let ny = -K; ny <= K; ny++) for (let nz = -K; nz <= K; nz++)
    for (let px = 0; px < 2; px++) for (let py = 0; py < 2; py++) for (let pz = 0; pz < 2; pz++) {
      const k = Math.abs(nx - px) + Math.abs(nx) + Math.abs(ny - py) + Math.abs(ny) + Math.abs(nz - pz) + Math.abs(nz);
      if (k > K) continue;
      const img = [(1 - 2 * px) * src[0] + 2 * nx * room[0], (1 - 2 * py) * src[1] + 2 * ny * room[1], (1 - 2 * pz) * src[2] + 2 * nz * room[2]];
      const g = beta ** k;
      if (k > 0) early += g * g / (16 * Math.PI ** 2 * dist3(img, cen) ** 2);
      mics.forEach((m, mi) => {
        const d = Math.max(dist3(img, m), 0.01), delay = d / C * FS, amp = g / (4 * Math.PI * d);
        const n0 = Math.floor(delay);
        for (let t = n0 - TAPS + 1; t <= n0 + TAPS; t++) {
          if (t < 0 || t >= Lr) continue;
          const x = t - delay, w = 0.5 + 0.5 * Math.cos(Math.PI * x / (TAPS + 1));
          h[mi][t] += amp * w * (Math.abs(x) < 1e-9 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x));
        }
      });
    }
  // diffuse late tail: decaying noise arriving from P random directions, delayed per mic
  const lateOf = a => Math.max(0, (1 - a) / (Math.PI * S * a) - early);
  const tailLen = Math.round(Math.min(rt60, 1.5) * FS);
  const start = Math.max(0, Math.round(dist3(src, cen) / C * FS + 0.004 * FS) - 8);
  const L2 = nextPow2(tailLen + 32), P = 24, half = L2 / 2, damp = damping > 0;
  const mkEnv = rt => { const e = new Float64Array(tailLen); let s = 0; for (let t = 0; t < tailLen; t++) { e[t] = Math.exp(-6.9078 * t / (rt * FS)) * Math.min(1, t / (0.01 * FS)); s += e[t] ** 2; } return [e, s]; };
  const [env, envE] = mkEnv(rt60), [envH, envEH] = damp ? mkEnv(rt60Hf) : [null, 0];
  const sigma = Math.sqrt(lateOf(alpha) / (P * envE)), sigmaH = damp ? Math.sqrt(lateOf(alphaH) / (P * envEH)) : 0;
  // low/high split for damping: raised-cosine crossover 1.5-2.5 kHz applied in the frequency domain (W_L + W_H = 1).
  // Low band keeps rt60, high band gets rt60Hf. (A time-domain 2-pole split leaked the slow low-band tail ~9 dB down
  // into the high band, which hid the faster HF decay.)
  const WL = damp ? new Float64Array(half + 1) : null;
  if (damp) for (let k = 0; k <= half; k++) { const f = k * FS / L2; WL[k] = f <= 1500 ? 1 : f >= 2500 ? 0 : 0.5 + 0.5 * Math.cos(Math.PI * (f - 1500) / 1000); }
  const Tr = mics.map(() => new Float64Array(L2)), Ti = mics.map(() => new Float64Array(L2));
  const nr = new Float64Array(L2), ni = new Float64Array(L2), hr = damp ? new Float64Array(L2) : null, hi = damp ? new Float64Array(L2) : null;
  for (let p = 0; p < P; p++) {
    const z = 2 * rng.u() - 1, phi = 2 * Math.PI * rng.u(), s = Math.sqrt(1 - z * z);
    const u = [s * Math.cos(phi), s * Math.sin(phi), z];
    nr.fill(0); ni.fill(0);
    if (!damp) { for (let t = 0; t < tailLen; t++) nr[t] = sigma * env[t] * rng.g(); fft(nr, ni, false); }
    else {
      hr.fill(0); hi.fill(0);
      for (let t = 0; t < tailLen; t++) { const g = rng.g(); nr[t] = sigma * env[t] * g; hr[t] = sigmaH * envH[t] * g; }
      fft(nr, ni, false); fft(hr, hi, false);
      for (let k = 0; k < L2; k++) { const w = WL[Math.min(k, L2 - k)]; nr[k] = w * nr[k] + (1 - w) * hr[k]; ni[k] = w * ni[k] + (1 - w) * hi[k]; }
    }
    mics.forEach((m, mi) => {
      const tau = ((m[0] - cen[0]) * u[0] + (m[1] - cen[1]) * u[1] + (m[2] - cen[2]) * u[2]) / C * FS - 8;   // arrives earlier toward u
      const dl = 2 * Math.PI * tau / L2, cd = Math.cos(dl), sd = Math.sin(dl), TR = Tr[mi], TI = Ti[mi];
      let c = 1, sn = 0;   // phase recurrence instead of a cos/sin per bin; the negative half is the conjugate
      for (let k = 0; k <= half; k++) {
        const a = nr[k] * c - ni[k] * sn, b = nr[k] * sn + ni[k] * c;
        TR[k] += a; TI[k] += b;
        if (k > 0 && k < half) { TR[L2 - k] += a; TI[L2 - k] -= b; }
        const c2 = c * cd - sn * sd; sn = sn * cd + c * sd; c = c2;
      }
    });
  }
  mics.forEach((_, mi) => {
    fft(Tr[mi], Ti[mi], true);
    for (let t = 0; t < L2 && start + t < Lr; t++) h[mi][start + t] += Tr[mi][t];
  });
  return h;
}

// Convolve one source with its M RIRs (two real channels per complex FFT; an odd leftover is paired with silence).
// Returns M channels of length N.
function engConvolve(sig, h, NF) {
  const M = h.length, sr = new Float64Array(NF), si = new Float64Array(NF);
  sr.set(sig.subarray ? sig.subarray(0, Math.min(sig.length, NF)) : sig);
  fft(sr, si, false);
  const out = [];
  for (let m = 0; m < M; m += 2) {
    const ar = new Float64Array(NF), ai = new Float64Array(NF), two = m + 1 < M;
    ar.set(h[m]); if (two) ai.set(h[m + 1]);
    fft(ar, ai, false);
    // split the paired spectra, multiply by the source, and re-pair for one inverse FFT
    const zr = new Float64Array(NF), zi = new Float64Array(NF);
    for (let k = 0; k < NF; k++) {
      const j = (NF - k) % NF;
      const h0r = (ar[k] + ar[j]) / 2, h0i = (ai[k] - ai[j]) / 2;
      const h1r = (ai[k] + ai[j]) / 2, h1i = -(ar[k] - ar[j]) / 2;
      const y0r = h0r * sr[k] - h0i * si[k], y0i = h0r * si[k] + h0i * sr[k];
      const y1r = h1r * sr[k] - h1i * si[k], y1i = h1r * si[k] + h1i * sr[k];
      zr[k] = y0r - y1i; zi[k] = y0i + y1r;
    }
    fft(zr, zi, true);
    out.push(zr.slice(0, N)); if (two) out.push(zi.slice(0, N));
  }
  return out;
}
const energy = x => { let s = 0; for (let i = 0; i < x.length; i++) s += x[i] * x[i]; return s; };
function scaleAll(chs, g) { for (const c of chs) for (let i = 0; i < c.length; i++) c[i] *= g; return chs; }
function addInto(dst, src, g = 1) { for (let m = 0; m < dst.length; m++) for (let i = 0; i < N; i++) dst[m][i] += g * src[m][i]; }
const engZeros = M => Array.from({ length: M }, () => new Float64Array(N));

// ---------------------------------------------------------------- STFT / beamforming
const WIN = Float64Array.from({ length: NFFT }, (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / NFFT));
const NB = NFFT / 2 + 1, PAD = NFFT / 2;
const NFR = Math.floor((N + 2 * PAD - NFFT) / HOP) + 1;
// STFT of a pair of real signals in one complex FFT per frame -> two arrays [frame*NB] re/im
function stftPair(x, y, frame, out0, out1) {
  const re = new Float64Array(NFFT), im = new Float64Array(NFFT), s = frame * HOP - PAD;
  for (let i = 0; i < NFFT; i++) { const t = s + i; if (t >= 0 && t < N) { re[i] = x[t] * WIN[i]; im[i] = y ? y[t] * WIN[i] : 0; } }
  fft(re, im, false);
  for (let k = 0; k < NB; k++) {
    const j = (NFFT - k) % NFFT;
    out0[2 * k] = (re[k] + re[j]) / 2; out0[2 * k + 1] = (im[k] - im[j]) / 2;
    if (out1) { out1[2 * k] = (im[k] + im[j]) / 2; out1[2 * k + 1] = -(re[k] - re[j]) / 2; }
  }
}
// all channels of one frame: Float64Array [M][NB*2]
function engFrames(chs, f) {
  const M = chs.length, out = Array.from({ length: M }, () => new Float64Array(2 * NB));
  for (let m = 0; m < M; m += 2) stftPair(chs[m], chs[m + 1], f, out[m], m + 1 < M ? out[m + 1] : null);
  return out;
}
function steer(rel, az, el) {   // [NB][M] complex, exp(+j 2 pi f (r . u)/c), u = unit vector toward the source (3D)
  const M = rel.length, a = az * Math.PI / 180, e = el * Math.PI / 180;
  const u = [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
  const d = new Float64Array(NB * M * 2);
  for (let k = 0; k < NB; k++) for (let m = 0; m < M; m++) {
    const ph = 2 * Math.PI * (k * FS / NFFT) * (rel[m][0] * u[0] + rel[m][1] * u[1] + rel[m][2] * u[2]) / C;
    d[(k * M + m) * 2] = Math.cos(ph); d[(k * M + m) * 2 + 1] = Math.sin(ph);
  }
  return d;
}
function solve(Ar, Ai, br, bi, n) {
  const ar = Float64Array.from(Ar), ai = Float64Array.from(Ai), xr = Float64Array.from(br), xi = Float64Array.from(bi);
  for (let k = 0; k < n; k++) {
    let p = k, best = 0;
    for (let i = k; i < n; i++) { const v = ar[i * n + k] ** 2 + ai[i * n + k] ** 2; if (v > best) { best = v; p = i; } }
    if (p !== k) {
      for (let j = 0; j < n; j++) { let t = ar[k * n + j]; ar[k * n + j] = ar[p * n + j]; ar[p * n + j] = t; t = ai[k * n + j]; ai[k * n + j] = ai[p * n + j]; ai[p * n + j] = t; }
      let t = xr[k]; xr[k] = xr[p]; xr[p] = t; t = xi[k]; xi[k] = xi[p]; xi[p] = t;
    }
    const pr = ar[k * n + k], pi = ai[k * n + k], den = pr * pr + pi * pi || 1e-30;
    for (let i = k + 1; i < n; i++) {
      const fr = (ar[i * n + k] * pr + ai[i * n + k] * pi) / den, fi = (ai[i * n + k] * pr - ar[i * n + k] * pi) / den;
      for (let j = k; j < n; j++) { const r = ar[k * n + j], q = ai[k * n + j]; ar[i * n + j] -= fr * r - fi * q; ai[i * n + j] -= fr * q + fi * r; }
      xr[i] -= fr * xr[k] - fi * xi[k]; xi[i] -= fr * xi[k] + fi * xr[k];
    }
  }
  for (let i = n - 1; i >= 0; i--) {
    let sr = xr[i], si = xi[i];
    for (let j = i + 1; j < n; j++) { sr -= ar[i * n + j] * xr[j] - ai[i * n + j] * xi[j]; si -= ar[i * n + j] * xi[j] + ai[i * n + j] * xr[j]; }
    const pr = ar[i * n + i], pi = ai[i * n + i], den = pr * pr + pi * pi || 1e-30;
    xr[i] = (sr * pr + si * pi) / den; xi[i] = (si * pr - sr * pi) / den;
  }
  return [xr, xi];
}
// MPDR weights per bin from covariance R [NB][M*M] (re, im)
function mpdr(Rr, Ri, d, M) {
  const w = new Float64Array(NB * M * 2);
  for (let k = 0; k < NB; k++) {
    const rr = Rr.subarray(k * M * M, (k + 1) * M * M), ri = Ri.subarray(k * M * M, (k + 1) * M * M);
    const L = Float64Array.from(rr);
    let tr = 0; for (let m = 0; m < M; m++) tr += rr[m * M + m];
    for (let m = 0; m < M; m++) L[m * M + m] += 1e-3 * tr / M + 1e-12;
    const dr = new Float64Array(M), di = new Float64Array(M);
    for (let m = 0; m < M; m++) { dr[m] = d[(k * M + m) * 2]; di[m] = d[(k * M + m) * 2 + 1]; }
    const [yr, yi] = solve(L, ri, dr, di, M);
    let nr = 0, ni = 0;
    for (let m = 0; m < M; m++) { nr += dr[m] * yr[m] + di[m] * yi[m]; ni += dr[m] * yi[m] - di[m] * yr[m]; }
    const den = nr * nr + ni * ni || 1e-30;
    for (let m = 0; m < M; m++) { w[(k * M + m) * 2] = (yr[m] * nr + yi[m] * ni) / den; w[(k * M + m) * 2 + 1] = (yi[m] * nr - yr[m] * ni) / den; }
  }
  return w;
}
function das(d, M) { return d.map(x => x / M); }
// y = w^H x for one frame
function applyFrame(w, fr, out, M) {
  for (let k = 0; k < NB; k++) {
    let yr = 0, yi = 0;
    for (let m = 0; m < M; m++) {
      const wr = w[(k * M + m) * 2], wi = w[(k * M + m) * 2 + 1], xr = fr[m][2 * k], xi = fr[m][2 * k + 1];
      yr += wr * xr + wi * xi; yi += wr * xi - wi * xr;
    }
    out[2 * k] = yr; out[2 * k + 1] = yi;
  }
}
function istftAdd(spec, f, acc, norm) {
  const re = new Float64Array(NFFT), im = new Float64Array(NFFT);
  for (let k = 0; k < NB; k++) { re[k] = spec[2 * k]; im[k] = spec[2 * k + 1]; if (k > 0 && k < NFFT / 2) { re[NFFT - k] = spec[2 * k]; im[NFFT - k] = -spec[2 * k + 1]; } }
  fft(re, im, true);
  const s = f * HOP - PAD;
  for (let i = 0; i < NFFT; i++) { const t = s + i; if (t >= 0 && t < N) { acc[t] += re[i] * WIN[i]; if (norm) norm[t] += WIN[i] * WIN[i]; } }
}
function accumulateCov(chs, Rr, Ri, weight) {
  const M = chs.length;
  for (let f = 0; f < NFR; f++) {
    const fr = engFrames(chs, f);
    for (let k = 0; k < NB; k++) {
      const base = k * M * M;
      for (let i = 0; i < M; i++) {
        const xr = fr[i][2 * k], xi = fr[i][2 * k + 1];
        for (let j = i; j < M; j++) {   // Hermitian: compute j >= i, mirror the rest
          const yr = fr[j][2 * k], yi = fr[j][2 * k + 1];
          const a = weight * (xr * yr + xi * yi), b = weight * (xi * yr - xr * yi);
          Rr[base + i * M + j] += a; Ri[base + i * M + j] += b;
          if (j !== i) { Rr[base + j * M + i] += a; Ri[base + j * M + i] -= b; }
        }
      }
    }
  }
}

// SRP-PHAT on the mixture covariance. grid[az] = the azimuth map peaks are picked on (see below).
// For a PLANAR ring the delays depend only on cos(el): el and -el are indistinguishable and the size of el is only seen
// as a shrink of all delays, which reverberation mimics (in tests in-plane talkers came out 45-90 deg "up"). So a planar
// ring reports el = null (unknown). A source straight above gives zero delays at every azimuth: its azimuth is undefined.
// A dual ring has a vertical baseline (ringGap), so el is estimated per peak (-60..90 in 15 deg steps), coarsely.
function engSrp(Rr, Ri, rel, nsrc) {
  const M = rel.length, planar = rel.every(r => Math.abs(r[2] - rel[0][2]) < 1e-9);
  const els = planar ? [0] : [-60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90];
  const kLo = Math.ceil(300 * NFFT / FS), kHi = Math.floor(3500 * NFFT / FS), nk = kHi - kLo + 1;
  const pi = [], pj = [];
  for (let i = 0; i < M; i++) for (let j = i + 1; j < M; j++) { pi.push(i); pj.push(j); }
  const NP = pi.length, ar = new Float64Array(NP * nk), ai = new Float64Array(NP * nk);
  for (let q = 0; q < NP; q++) for (let k = kLo; k <= kHi; k++) {
    const idx = k * M * M + pi[q] * M + pj[q], rr = Rr[idx], ri = Ri[idx], mag = Math.hypot(rr, ri) || 1;
    ar[q * nk + k - kLo] = rr / mag; ai[q * nk + k - kLo] = ri / mag;
  }
  // Azimuth peaks come from the el = 0 slice (the v1 map). Taking the max over elevation first let diffuse/reverberant energy,
  // which a small planar ring cannot place in elevation, pile up at high elevations and turned the flat zenith row into
  // spurious plateau-edge peaks. Elevation is then estimated per peak, at that azimuth.
  const dw = 2 * Math.PI * (FS / NFFT) / C, E = els.length, map = els.map(() => new Float64Array(360));
  els.forEach((el, ei) => {
    const ce = Math.cos(el * Math.PI / 180), se = Math.sin(el * Math.PI / 180);
    for (let az = 0; az < 360; az++) {
      const u0 = ce * Math.cos(az * Math.PI / 180), u1 = ce * Math.sin(az * Math.PI / 180), u2 = se;
      let sum = 0;
      for (let q = 0; q < NP; q++) {
        const a = rel[pi[q]], b = rel[pj[q]];
        const delta = dw * ((b[0] - a[0]) * u0 + (b[1] - a[1]) * u1 + (b[2] - a[2]) * u2);
        const cd = Math.cos(delta), sd = Math.sin(delta), ph0 = kLo * delta;
        let c = Math.cos(ph0), s = Math.sin(ph0);
        const o = q * nk;
        for (let k = 0; k < nk; k++) {
          sum += ar[o + k] * c - ai[o + k] * s;
          const c2 = c * cd - s * sd; s = s * cd + c * sd; c = c2;
        }
      }
      map[ei][az] = sum;
    }
  });
  // planar: the el = 0 slice. Dual ring: max over elevation (it has real elevation information, and a source well above
  // the plane is mis-aimed in azimuth on the el = 0 slice).
  const grid = planar ? map[0] : Float64Array.from(map[0], (_, az) => Math.max(...map.map(m => m[az])));
  let lo = Infinity, hi = -Infinity; for (const v of grid) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const pk = [];
  for (let g = 0; g < 360; g++) if (grid[g] >= grid[(g + 359) % 360] && grid[g] > grid[(g + 1) % 360]) pk.push(g);
  pk.sort((a, b) => grid[b] - grid[a]);
  const chosen = pk.slice(0, nsrc);
  if (chosen.length < nsrc) {   // flat grid (e.g. a source at the zenith): fill with the best azimuths not already close to a peak
    const rest = Array.from({ length: 360 }, (_, g) => g).sort((a, b) => grid[b] - grid[a]);
    for (const g of rest) {
      if (chosen.length >= nsrc) break;
      if (chosen.every(c => Math.min(Math.abs(c - g), 360 - Math.abs(c - g)) >= 15)) chosen.push(g);
    }
  }
  const elAt = az => { if (planar) return null; let best = 0; for (let ei = 1; ei < E; ei++) if (map[ei][az] > map[best][az]) best = ei; return els[best]; };
  let peaks = chosen.map(az => ({ az, el: elAt(az) }));
  const zen = peaks.filter(q => q.el === 90);   // every azimuth is the same point at the zenith: keep one (the strongest)
  if (zen.length > 1) { const keep = zen.reduce((a, b) => (map[E - 1][b.az] > map[E - 1][a.az] ? b : a)); peaks = peaks.filter(q => q.el !== 90 || q === keep); }
  return { grid: Array.from(grid, v => (v - lo) / (hi - lo || 1)), peaks: peaks.sort((a, b) => a.az - b.az) };
}

// ---------------------------------------------------------------- the scene
function robotSignals(p, seed) {
  const rng = makeRng(seed), ms = motorState(p.fanRpm);
  return {
    fan: () => makeFan(ms, rng), neck: () => makeServo(ms.neck, 600, 2400, rng), shoulders: () => makeServo(ms.sh, 450, 1800, rng),
    footsteps: () => makeFootsteps(ms, rng), clicks: () => makeClicks(ms, rng), hum: () => makeHum(rng), ms,
  };
}
function engResample(x, f) {   // linear interpolation, reads x at f samples per output sample (f < 1 = slower, lower pitch)
  const n = Math.floor((x.length - 1) / f), out = new Float64Array(n);
  for (let i = 0; i < n; i++) { const pos = i * f, i0 = Math.floor(pos), fr = pos - i0; out[i] = x[i0] * (1 - fr) + x[Math.min(i0 + 1, x.length - 1)] * fr; }
  return out;
}
function engVoice(name, voices, cache) {
  if (name === "male_low") return cache.male_low || (cache.male_low = engResample(voices.male, 0.85));
  if (name === "female_high") return cache.female_high || (cache.female_high = engResample(voices.female, 1.15));
  return voices[name];
}
const engHash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = (Math.imul(h, 33) + s.charCodeAt(i)) | 0; return h >>> 0; };
// raised-cosine partition of unity over 4 static segments centred at 0, N/3, 2N/3, N
function engSegWeights() {
  const Wd = N / 3;
  return [0, 1, 2, 3].map(j => { const w = new Float64Array(N); for (let i = 0; i < N; i++) { const d = Math.abs(i - j * Wd); if (d < Wd) w[i] = 0.5 + 0.5 * Math.cos(Math.PI * d / Wd); } return w; });
}

function render(p0, voices, progress = () => {}) {
  const t0 = Date.now();
  const p = normalizeParams(p0), warnings = p._warnings.slice();
  const room = [p.roomL, p.roomW, p.roomH], cen = [p.arrayX, p.arrayY, p.arrayH];
  const mics = engMicPositions(p, cen), M = mics.length, rel = mics.map(m => [m[0] - cen[0], m[1] - cen[1], m[2] - cen[2]]);
  const tailLen = Math.round(Math.min(p.rt60, 1.5) * FS);
  const Lr = nextPow2(Math.max(1200, 260 + tailLen) + 64), NF = nextPow2(N + Lr);
  const rirRng = makeRng(7), vcache = {};
  const rirFor = pos => engRoomRirs(pos, mics, cen, room, p.rt60, p.damping, Lr, rirRng);
  const place = (sig, start) => { const out = new Float64Array(N), s = Math.round(start * FS); for (let i = 0; i < sig.length && s + i < N; i++) out[s + i] = sig[i]; return out; };
  const sources = [], talk = {}, solo = {}, tgt = [];   // tgt: {sid, y} target speakers with all channels
  const bg = engZeros(M);
  const note = (label, pl) => { if (pl.clamped) warnings.push(label + " was outside the room and moved to stay 0.2 m inside it (now az " + pl.az.toFixed(0) + ", el " + pl.el.toFixed(0) + ", " + pl.dist.toFixed(2) + " m)."); };

  // ---- speakers (loudness relative to speaker 1 at mic 1)
  let ref = 0;
  p.speakers.forEach((s, i) => {
    progress("Placing speaker " + (i + 1) + " of " + p.speakers.length);
    const label = "Speaker " + (i + 1) + " (" + s.voice.replace("_", " ") + ")";
    const pl = engPlace(cen, room, s.az, s.el, s.dist, p._legacy ? 0.1 : 0.2); note(label, pl);   // legacy v1 scenes may sit 0.15 m from a wall
    const v = engVoice(s.voice, voices, vcache), st = Math.round(s.start * FS);
    let sig;
    if (s.voice === "baby") { sig = new Float64Array(N); for (let k = st; k < N; k++) sig[k] = v[(k - st) % v.length]; }
    else sig = place(v, s.start);
    talk[s.id] = [s.start, s.voice === "baby" ? DUR : Math.min(DUR, s.start + v.length / FS)];
    const y = engConvolve(sig, rirFor(pl.pos), NF);
    if (i === 0) ref = energy(y[0]) || 1e-30;
    else { const e = energy(y[0]); if (e > 0) scaleAll(y, Math.sqrt(ref / e * 10 ** (s.db / 10))); }
    sources.push({ id: s.id, kind: "speaker", label, voice: s.voice, az: pl.az, el: pl.el, dist: pl.dist, clamped: pl.clamped, target: s.target });
    solo[s.id] = y[0];
    if (s.target) tgt.push({ sid: s.id, az: pl.az, el: pl.el, y }); else addInto(bg, y);
  });

  // ---- ambient noise sources from the scenario (NOISE_GEN lives in scenarios.js, resolved at call time)
  const gens = typeof NOISE_GEN !== "undefined" ? NOISE_GEN : {};
  let segW = null;
  p.noises.forEach((n, i) => {
    if (!n.on) return;
    const gen = gens[n.gen];
    if (typeof gen !== "function") { warnings.push("Noise '" + n.label + "': unknown generator '" + n.gen + "', skipped."); return; }
    progress("Adding noise: " + n.label);
    let raw = gen(makeRng(1000 + engHash(n.id)), p, voices);
    let sig = raw instanceof Float64Array && raw.length === N ? raw : Float64Array.from({ length: N }, (_, k) => (raw && raw[k]) || 0);
    const esig = energy(sig);
    if (!(esig > 0) || !Number.isFinite(esig)) { warnings.push("Noise '" + n.label + "': generator returned silence or non-finite values, skipped."); return; }
    const p1 = engPlace(cen, room, n.az, n.el, n.dist, 0.2); note("Noise '" + n.label + "'", p1);
    let y;
    if (!n.path) y = engConvolve(sig, rirFor(p1.pos), NF);
    else {
      const e1 = n.path, shortArc = ((e1.az1 - n.az + 540) % 360) - 180;
      segW = segW || engSegWeights();
      y = engZeros(M);
      let endPl = null;
      for (let j = 0; j < 4; j++) {
        const f = j / 3, pl = engPlace(cen, room, n.az + shortArc * f, n.el + (e1.el1 - n.el) * f, n.dist + (e1.dist1 - n.dist) * f, 0.2);
        if (j === 3) { endPl = pl; note("Noise '" + n.label + "' (end of path)", pl); }
        const seg = new Float64Array(N); for (let k = 0; k < N; k++) seg[k] = sig[k] * segW[j][k];
        addInto(y, engConvolve(seg, rirFor(pl.pos), NF));
      }
      p1.endAz = endPl.az; p1.endEl = endPl.el; p1.endDist = endPl.dist;
    }
    const e = energy(y[0]);
    if (e > 0) scaleAll(y, Math.sqrt(ref / e * 10 ** (n.db / 10)));
    addInto(bg, y); solo[n.id] = y[0];
    const src = { id: n.id, kind: "noise", label: n.label, gen: n.gen, az: p1.az, el: p1.el, dist: p1.dist, clamped: p1.clamped };
    if (n.path) { src.path = { az1: p1.endAz, el1: p1.endEl, dist1: p1.endDist }; }
    sources.push(src);
  });

  // ---- the robot's own noises (fixed positions on the body, follow the array)
  const robotRir = {};
  const robotTake = (seed, keepSolo) => {
    const sigs = robotSignals(p, seed), total = engZeros(M);
    for (const k of ROBOT_KEYS) {
      if (!p[k + "On"]) continue;
      let y;
      if (k === "hum") { const h = sigs.hum(); y = Array.from({ length: M }, () => h.slice()); }
      else { robotRir[k] = robotRir[k] || rirFor(engRobotPlace(cen, room, k).pos); y = engConvolve(sigs[k](), robotRir[k], NF); }
      const e = energy(y[0]);
      if (e > 0) scaleAll(y, Math.sqrt(ref / e * 10 ** (p[k + "Db"] / 10)));
      addInto(total, y);
      if (keepSolo) solo[k] = y[0];
    }
    return { total, ms: sigs.ms };
  };
  progress("Running the robot's motors");
  const robot = robotTake(1, true);
  addInto(bg, robot.total);
  for (const k of ROBOT_KEYS) if (p[k + "On"]) {
    if (k === "hum") sources.push({ id: "hum", kind: "robot", label: ENG_ROBOT_LABEL.hum, az: 0, el: 0, dist: 0, clamped: false });
    else { const rp = engRobotPlace(cen, room, k); if (rp.clamped) warnings.push(ENG_ROBOT_LABEL[k] + " (on the robot body) was outside the room and moved inside it."); sources.push({ id: k, kind: "robot", label: ENG_ROBOT_LABEL[k], az: rp.az, el: rp.el, dist: rp.dist, clamped: rp.clamped }); }
  }
  const noiseRng = makeRng(11), roomStd = Math.sqrt(ref / N / 10 ** (p.roomDb / 10));
  const roomNoise = engZeros(M);
  for (const c of roomNoise) for (let i = 0; i < N; i++) c[i] = roomStd * noiseRng.g();
  addInto(bg, roomNoise);
  const anyRobot = ROBOT_KEYS.some(k => p[k + "On"]);

  const mix = engZeros(M);
  for (const t of tgt) addInto(mix, t.y);
  addInto(mix, bg);

  // ---- covariances: mixture, and mixture + a separate robot-only take (what the robot can record with nobody talking)
  progress("Learning the beamformers");
  const MM = NB * M * M;
  const Rr = new Float64Array(MM), Ri = new Float64Array(MM);
  accumulateCov(mix, Rr, Ri, 1 / NFR);
  let LRr = Rr, LRi = Ri;
  if (anyRobot) {
    const take = robotTake(99, false).total;
    for (let m = 0; m < M; m++) for (let i = 0; i < N; i++) take[m][i] += roomNoise[m][N - 1 - i];
    const Tr = new Float64Array(MM), Ti = new Float64Array(MM);
    accumulateCov(take, Tr, Ti, 1);
    LRr = new Float64Array(MM); LRi = new Float64Array(MM);
    for (let q = 0; q < MM; q++) { LRr[q] = (Rr[q] * NFR + 9 * Tr[q]) / (2 * NFR); LRi[q] = (Ri[q] * NFR + 9 * Ti[q]) / (2 * NFR); }
  }
  const beams = [];
  tgt.forEach((t, ti) => {
    const d = steer(rel, t.az, t.el);
    beams.push({ id: t.sid + "_das", ti, w: das(d, M) });
    beams.push({ id: t.sid + "_mvdr", ti, w: mpdr(Rr, Ri, d, M) });
    if (anyRobot) beams.push({ id: t.sid + "_learned", ti, w: mpdr(LRr, LRi, d, M) });
  });

  // ---- apply: outputs (from the mixture) and scores (target vs everything else)
  progress("Listening through each beam");
  const outAcc = beams.map(() => new Float64Array(N)), norm = new Float64Array(N);
  const pw = beams.map(() => ({ t: 0, r: 0 }));
  const y = new Float64Array(2 * NB), yt = new Float64Array(2 * NB);
  for (let f = 0; f < NFR; f++) {
    const fx = engFrames(mix, f), ft = tgt.map(t => engFrames(t.y, f));
    beams.forEach((b, bi) => {
      applyFrame(b.w, fx, y, M);
      istftAdd(y, f, outAcc[bi], bi === 0 ? norm : null);
      applyFrame(b.w, ft[b.ti], yt, M);
      for (let k = 0; k < 2 * NB; k++) { pw[bi].t += yt[k] ** 2; pw[bi].r += (y[k] - yt[k]) ** 2; }
    });
  }
  outAcc.forEach(a => { for (let i = 0; i < N; i++) a[i] /= Math.max(norm[i], 1e-9); });

  // ---- SRP-PHAT on the mixture: where does the robot think sound comes from?
  progress("Locating the sources");
  const srp = engSrp(Rr, Ri, rel, p.speakers.length);

  // ---- scale like Python: one gain for everything so levels compare
  let peak = 0; for (const c of mix) for (let i = 0; i < N; i++) peak = Math.max(peak, Math.abs(c[i]));
  const sc = 0.9 / (peak || 1);
  const f32 = (x, g = sc) => Float32Array.from(x, v => v * g);
  const norm07 = x => { let m = 0; for (const v of x) m = Math.max(m, Math.abs(v)); return f32(x, 0.7 / (m || 1)); };
  const db = (a, b) => 10 * Math.log10(a / b);
  const scores = {};
  for (const t of tgt) scores["mic_" + t.sid] = db(energy(t.y[0]), energy(mix[0].map((v, i) => v - t.y[0][i])));
  beams.forEach((b, bi) => { scores[b.id] = db(pw[bi].t, pw[bi].r); });

  const tracks = { mic1: f32(mix[0]) };
  beams.forEach((b, bi) => { tracks[b.id] = f32(outAcc[bi]); });
  const solos = {};
  for (const k in solo) solos[k] = norm07(solo[k]);
  const step = FS / 100, ms = robot.ms, ds = a => Array.from({ length: Math.floor(N / step) }, (_, i) => a[i * step]);
  const V = room[0] * room[1] * room[2];
  return {
    mics: mix.map(c => f32(c)), tracks, solos, scores, srp, sources, talk, warnings,
    motor: { fan: ds(ms.fan), neck: ds(ms.neck), sh: ds(ms.sh), walk: ds(ms.walk) },
    room: { L: room[0], W: room[1], H: room[2], rt60: p.rt60, rt60Hf: engRt60Hf(p.rt60, p.damping), volume: V, damping: p.damping },
    micPositions: rel.map(r => r.map(v => Math.round(v * 1e5) / 1e5)),   // metres from the array centre, mic 1 first (x = az 0, z up)
    ms: Date.now() - t0,
  };
}

// PCM16/float WAV -> Float64Array (mono, first channel), trimmed and peak-normalised like sim_conversation._read
function readWav(buf, trim) {
  const v = new DataView(buf);
  let off = 12, fmt = null, data = null;
  while (off + 8 <= v.byteLength) {
    const id = String.fromCharCode(v.getUint8(off), v.getUint8(off + 1), v.getUint8(off + 2), v.getUint8(off + 3)), size = v.getUint32(off + 4, true);
    if (id === "fmt ") fmt = { tag: v.getUint16(off + 8, true), ch: v.getUint16(off + 10, true), rate: v.getUint32(off + 12, true), bits: v.getUint16(off + 22, true) };
    if (id === "data") data = { off: off + 8, size: Math.min(size, v.byteLength - off - 8) };
    off += 8 + size + (size & 1);
  }
  const bps = fmt.bits / 8, n = Math.floor(data.size / (bps * fmt.ch));
  let x = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const o = data.off + i * bps * fmt.ch;
    x[i] = fmt.bits === 16 ? v.getInt16(o, true) / 32768 : fmt.bits === 32 && fmt.tag === 3 ? v.getFloat32(o, true) : v.getInt32(o, true) / 2147483648;
  }
  if (trim !== undefined) {
    let m = 0; for (const s of x) m = Math.max(m, Math.abs(s));
    x = x.map(s => s / (m || 1));
    if (trim) {
      let a = 0, b = n - 1;
      while (a < n && Math.abs(x[a]) <= 0.02) a++;
      while (b > a && Math.abs(x[b]) <= 0.02) b--;
      x = x.slice(Math.max(0, a - 160), b + 160);
    }
  }
  return { x, rate: fmt.rate, channels: fmt.ch };
}

if (typeof module !== "undefined") module.exports = { render, readWav, FS, N };

if (typeof module !== "undefined") module.exports = { render, readWav, normalizeParams, FS, N, _test: { fft, engRoomRirs, engMicPositions, engSrp } };
if (typeof self !== "undefined" && typeof window === "undefined" && typeof module === "undefined") {
  let voices = null;
  self.onmessage = e => {
    const { id, params, voiceBufs } = e.data;
    if (voiceBufs) voices = { male: readWav(voiceBufs.male, true).x, female: readWav(voiceBufs.female, true).x, baby: readWav(voiceBufs.baby, false).x };
    try {
      const res = render(params, voices, msg => self.postMessage({ id, progress: msg }));
      const transfer = [...res.mics.map(a => a.buffer), ...Object.values(res.tracks).map(a => a.buffer), ...Object.values(res.solos).map(a => a.buffer)];
      self.postMessage({ id, res }, transfer);
    } catch (err) { self.postMessage({ id, error: String(err && err.stack || err) }); }
  };
}
