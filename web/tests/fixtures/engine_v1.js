// Robot Acoustic audio engine. Runs in a Web Worker (or Node for testing).
// Mirrors sim_conversation.py + sim_8mic_robot_noise.py: same geometry, voices,
// robot noise recipes, levels and MPDR beamformer. The room is lighter than
// pyroomacoustics: exact image sources up to 3 bounces plus a diffuse late tail.
"use strict";
const FS = 16000, DUR = 5.5, N = Math.round(DUR * FS), C = 343, NFFT = 512, HOP = 128, M = 8;
const ROOM = [6, 5, 3], CENTRE = [3, 2.5, 1.5];

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

// ---------------------------------------------------------------- room impulse responses
function micPositions(radius) {
  return Array.from({ length: M }, (_, i) => {
    const a = 2 * Math.PI * i / M;
    return [CENTRE[0] + radius * Math.cos(a), CENTRE[1] + radius * Math.sin(a), CENTRE[2]];
  });
}
const at = (deg, dist, dz = 0) => [CENTRE[0] + dist * Math.cos(deg * Math.PI / 180), CENTRE[1] + dist * Math.sin(deg * Math.PI / 180), CENTRE[2] + dz];
const dist3 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

function roomRirs(src, mics, rt60, Lr, rng) {
  const V = ROOM[0] * ROOM[1] * ROOM[2], S = 2 * (ROOM[0] * ROOM[1] + ROOM[0] * ROOM[2] + ROOM[1] * ROOM[2]);
  const alpha = Math.min(0.99, 0.161 * V / (S * rt60)), beta = Math.sqrt(1 - alpha);
  const h = mics.map(() => new Float64Array(Lr));
  const K = 3, TAPS = 16;
  let early = 0;
  for (let nx = -K; nx <= K; nx++) for (let ny = -K; ny <= K; ny++) for (let nz = -K; nz <= K; nz++)
    for (let px = 0; px < 2; px++) for (let py = 0; py < 2; py++) for (let pz = 0; pz < 2; pz++) {
      const k = Math.abs(nx - px) + Math.abs(nx) + Math.abs(ny - py) + Math.abs(ny) + Math.abs(nz - pz) + Math.abs(nz);
      if (k > K) continue;
      const img = [(1 - 2 * px) * src[0] + 2 * nx * ROOM[0], (1 - 2 * py) * src[1] + 2 * ny * ROOM[1], (1 - 2 * pz) * src[2] + 2 * nz * ROOM[2]];
      const g = beta ** k;
      if (k > 0) early += g * g / (16 * Math.PI ** 2 * dist3(img, CENTRE) ** 2);
      mics.forEach((m, mi) => {
        const d = dist3(img, m), delay = d / C * FS, amp = g / (4 * Math.PI * d);
        const n0 = Math.floor(delay);
        for (let t = n0 - TAPS + 1; t <= n0 + TAPS; t++) {
          if (t < 0 || t >= Lr) continue;
          const x = t - delay, w = 0.5 + 0.5 * Math.cos(Math.PI * x / (TAPS + 1));
          h[mi][t] += amp * w * (Math.abs(x) < 1e-9 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x));
        }
      });
    }
  // diffuse late tail: decaying noise arriving from P random directions, delayed per mic
  const late = Math.max(0, (1 - alpha) / (Math.PI * S * alpha) - early);
  const tailLen = Math.round(Math.min(rt60, 1.2) * FS);
  const start = Math.max(0, Math.round(dist3(src, CENTRE) / C * FS + 0.004 * FS) - 8);
  const L2 = nextPow2(tailLen + 32), P = 24;
  const env = new Float64Array(tailLen);
  let envE = 0;
  for (let t = 0; t < tailLen; t++) { env[t] = Math.exp(-6.9078 * t / (rt60 * FS)) * Math.min(1, t / (0.01 * FS)); envE += env[t] ** 2; }
  const sigma = Math.sqrt(late / (P * envE));
  const Tr = mics.map(() => new Float64Array(L2)), Ti = mics.map(() => new Float64Array(L2));
  const nr = new Float64Array(L2), ni = new Float64Array(L2);
  for (let p = 0; p < P; p++) {
    const z = 2 * rng.u() - 1, phi = 2 * Math.PI * rng.u(), s = Math.sqrt(1 - z * z);
    const u = [s * Math.cos(phi), s * Math.sin(phi), z];
    nr.fill(0); ni.fill(0);
    for (let t = 0; t < tailLen; t++) nr[t] = sigma * env[t] * rng.g();
    fft(nr, ni, false);
    mics.forEach((m, mi) => {
      const tau = ((m[0] - CENTRE[0]) * u[0] + (m[1] - CENTRE[1]) * u[1]) / C * FS - 8;   // arrives earlier toward u
      for (let k = 0; k < L2; k++) {
        const kk = k <= L2 / 2 ? k : k - L2, ph = 2 * Math.PI * kk * tau / L2;
        const c = Math.cos(ph), sn = Math.sin(ph);
        Tr[mi][k] += nr[k] * c - ni[k] * sn; Ti[mi][k] += nr[k] * sn + ni[k] * c;
      }
    });
  }
  mics.forEach((_, mi) => {
    fft(Tr[mi], Ti[mi], true);
    for (let t = 0; t < L2 && start + t < Lr; t++) h[mi][start + t] += Tr[mi][t];
  });
  return h;
}

// Convolve one source with its 8 RIRs; returns 8 channels of length N and the energy at mic 1.
function convolve8(sig, h, NF) {
  const sr = new Float64Array(NF), si = new Float64Array(NF);
  sr.set(sig.subarray ? sig.subarray(0, Math.min(sig.length, NF)) : sig);
  fft(sr, si, false);
  const out = [];
  for (let m = 0; m < M; m += 2) {
    const ar = new Float64Array(NF), ai = new Float64Array(NF);
    ar.set(h[m]); ai.set(h[m + 1]);
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
    out.push(zr.slice(0, N), zi.slice(0, N));
  }
  return out;
}
const energy = x => { let s = 0; for (let i = 0; i < x.length; i++) s += x[i] * x[i]; return s; };
function scaleAll(chs, g) { for (const c of chs) for (let i = 0; i < c.length; i++) c[i] *= g; return chs; }
function addInto(dst, src, g = 1) { for (let m = 0; m < dst.length; m++) for (let i = 0; i < N; i++) dst[m][i] += g * src[m][i]; }
const zeros8 = () => Array.from({ length: M }, () => new Float64Array(N));

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
// all 8 channels of one frame: returns Float64Array [M][NB*2]
function frame8(chs, f) {
  const out = Array.from({ length: M }, () => new Float64Array(2 * NB));
  for (let m = 0; m < M; m += 2) stftPair(chs[m], chs[m + 1], f, out[m], out[m + 1]);
  return out;
}
function steer(rel, deg) {   // [NB][M] complex, exp(+j 2 pi f (r . u)/c)
  const u = [Math.cos(deg * Math.PI / 180), Math.sin(deg * Math.PI / 180)];
  const d = new Float64Array(NB * M * 2);
  for (let k = 0; k < NB; k++) for (let m = 0; m < M; m++) {
    const ph = 2 * Math.PI * (k * FS / NFFT) * (rel[m][0] * u[0] + rel[m][1] * u[1]) / C;
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
function mpdr(Rr, Ri, d) {
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
function das(d) { return d.map(x => x / M); }
// y = w^H x for one frame
function applyFrame(w, fr, out) {
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
  for (let f = 0; f < NFR; f++) {
    const fr = frame8(chs, f);
    for (let k = 0; k < NB; k++) {
      const base = k * M * M;
      for (let i = 0; i < M; i++) {
        const xr = fr[i][2 * k], xi = fr[i][2 * k + 1];
        for (let j = 0; j < M; j++) {
          const yr = fr[j][2 * k], yi = fr[j][2 * k + 1];
          Rr[base + i * M + j] += weight * (xr * yr + xi * yi);
          Ri[base + i * M + j] += weight * (xi * yr - xr * yi);
        }
      }
    }
  }
}

// ---------------------------------------------------------------- the scene
const ROBOT_POS = { fan: at(180, 0.07, -0.03), neck: at(0, 0, -0.10), shoulders: at(90, 0.18, -0.30), footsteps: at(0, 0.10, -1.40), clicks: at(0, 0, -0.10) };
const ROBOT_KEYS = ["fan", "neck", "shoulders", "footsteps", "clicks", "hum"];

function robotSignals(p, seed) {
  const rng = makeRng(seed), ms = motorState(p.fanRpm);
  return {
    fan: () => makeFan(ms, rng), neck: () => makeServo(ms.neck, 600, 2400, rng), shoulders: () => makeServo(ms.sh, 450, 1800, rng),
    footsteps: () => makeFootsteps(ms, rng), clicks: () => makeClicks(ms, rng), hum: () => makeHum(rng), ms,
  };
}

function render(p, voices, progress = () => {}) {
  const t0 = Date.now();
  const mics = micPositions(p.radius / 100), rel = mics.map(m => [m[0] - CENTRE[0], m[1] - CENTRE[1]]);
  const tailLen = Math.round(Math.min(p.rt60, 1.2) * FS);
  const Lr = nextPow2(Math.max(1200, 260 + tailLen) + 64), NF = nextPow2(N + Lr);
  const rirRng = makeRng(7);
  const place = (sig, start) => { const out = new Float64Array(N), s = Math.round(start * FS); for (let i = 0; i < sig.length && s + i < N; i++) out[s + i] = sig[i]; return out; };
  const male = place(voices.male, 0.3), female = place(voices.female, 2.6);
  const baby = new Float64Array(N); for (let i = 0; i < N; i++) baby[i] = voices.baby[i % voices.baby.length];

  progress("Placing the man and the woman");
  const yM = convolve8(male, roomRirs(at(p.manAng, p.dist), mics, p.rt60, Lr, rirRng), NF);
  const ref = energy(yM[0]);
  const yF = convolve8(female, roomRirs(at(p.womanAng, p.dist), mics, p.rt60, Lr, rirRng), NF);
  scaleAll(yF, Math.sqrt(ref / energy(yF[0])));
  const solo = {};
  const bg = zeros8();
  if (p.babyOn) {
    progress("Adding the baby");
    const yB = convolve8(baby, roomRirs(at(p.babyAng, p.babyDist, -0.7), mics, p.rt60, Lr, rirRng), NF);
    scaleAll(yB, Math.sqrt(ref / energy(yB[0]) * 10 ** (p.babyDb / 10)));
    addInto(bg, yB); solo.baby = yB[0];
  }
  const robotRir = {};
  const robotTake = (seed, keepSolo) => {
    const sigs = robotSignals(p, seed), total = zeros8();
    for (const k of ROBOT_KEYS) {
      if (!p[k + "On"]) continue;
      let y;
      if (k === "hum") { const h = sigs.hum(); y = Array.from({ length: M }, () => h.slice()); }
      else { robotRir[k] = robotRir[k] || roomRirs(ROBOT_POS[k], mics, p.rt60, Lr, rirRng); y = convolve8(sigs[k](), robotRir[k], NF); }
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
  const noiseRng = makeRng(11), roomStd = Math.sqrt(ref / N / 10 ** (p.roomDb / 10));
  const roomNoise = zeros8();
  for (const c of roomNoise) for (let i = 0; i < N; i++) c[i] = roomStd * noiseRng.g();
  addInto(bg, roomNoise);
  const anyRobot = ROBOT_KEYS.some(k => p[k + "On"]);

  const mix = zeros8();
  addInto(mix, yM); addInto(mix, yF); addInto(mix, bg);

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
  for (const [who, ang] of [["man", p.manAng], ["woman", p.womanAng]]) {
    const d = steer(rel, ang);
    beams.push({ id: who + "_das", who, w: das(d) });
    beams.push({ id: who + "_mvdr", who, w: mpdr(Rr, Ri, d) });
    if (anyRobot) beams.push({ id: who + "_learned", who, w: mpdr(LRr, LRi, d) });
  }

  // ---- apply: outputs (from the mixture) and scores (target vs everything else)
  progress("Listening through each beam");
  const outAcc = beams.map(() => new Float64Array(N)), norm = new Float64Array(N);
  const pw = beams.map(() => ({ t: 0, r: 0 }));
  const y = new Float64Array(2 * NB), yt = new Float64Array(2 * NB);
  for (let f = 0; f < NFR; f++) {
    const fx = frame8(mix, f), fm = frame8(yM, f), ff = frame8(yF, f);
    beams.forEach((b, bi) => {
      applyFrame(b.w, fx, y);
      istftAdd(y, f, outAcc[bi], bi === 0 ? norm : null);
      applyFrame(b.w, b.who === "man" ? fm : ff, yt);
      for (let k = 0; k < 2 * NB; k++) { pw[bi].t += yt[k] ** 2; pw[bi].r += (y[k] - yt[k]) ** 2; }
    });
  }
  outAcc.forEach(a => { for (let i = 0; i < N; i++) a[i] /= Math.max(norm[i], 1e-9); });

  // ---- SRP-PHAT on the mixture: where does the robot think sound comes from?
  const grid = new Float64Array(360);
  const kLo = Math.ceil(300 * NFFT / FS), kHi = Math.floor(3500 * NFFT / FS);
  for (let k = kLo; k <= kHi; k++) {
    const base = k * M * M, f = k * FS / NFFT;
    for (let g = 0; g < 360; g++) {
      const u = [Math.cos(g * Math.PI / 180), Math.sin(g * Math.PI / 180)];
      let s = 0;
      for (let i = 0; i < M; i++) for (let j = 0; j < M; j++) {
        if (i === j) continue;
        const rr = Rr[base + i * M + j], ri = Ri[base + i * M + j], mag = Math.hypot(rr, ri) || 1;
        const ph = 2 * Math.PI * f * ((rel[j][0] - rel[i][0]) * u[0] + (rel[j][1] - rel[i][1]) * u[1]) / C;
        s += (rr * Math.cos(ph) - ri * Math.sin(ph)) / mag;
      }
      grid[g] += s;
    }
  }
  const nsrc = 2 + (p.babyOn ? 1 : 0);
  const pk = [];
  for (let g = 0; g < 360; g++) if (grid[g] >= grid[(g + 359) % 360] && grid[g] > grid[(g + 1) % 360]) pk.push(g);
  pk.sort((a, b) => grid[b] - grid[a]);
  let lo = Infinity, hi = -Infinity; for (const v of grid) { lo = Math.min(lo, v); hi = Math.max(hi, v); }

  // ---- scale like Python: one gain for everything so levels compare
  let peak = 0; for (const c of mix) for (let i = 0; i < N; i++) peak = Math.max(peak, Math.abs(c[i]));
  const sc = 0.9 / peak;
  const f32 = (x, g = sc) => Float32Array.from(x, v => v * g);
  const norm07 = x => { let m = 0; for (const v of x) m = Math.max(m, Math.abs(v)); return f32(x, 0.7 / (m || 1)); };
  const db = (a, b) => 10 * Math.log10(a / b);
  const restAt1 = new Float64Array(N);
  const scores = {
    mic_man: db(energy(yM[0]), energy(mix[0].map((v, i) => v - yM[0][i]))),
    mic_woman: db(energy(yF[0]), energy(mix[0].map((v, i) => v - yF[0][i]))),
  };
  beams.forEach((b, bi) => { scores[b.id] = db(pw[bi].t, pw[bi].r); });
  void restAt1;

  const tracks = { mic1: f32(mix[0]) };
  beams.forEach((b, bi) => { tracks[b.id] = f32(outAcc[bi]); });
  const solos = { man: norm07(yM[0]), woman: norm07(yF[0]) };
  for (const k in solo) solos[k] = norm07(solo[k]);
  const step = FS / 100, ms = robot.ms, ds = a => Array.from({ length: Math.floor(N / step) }, (_, i) => a[i * step]);
  return {
    mics: mix.map(c => f32(c)), tracks, solos, scores,
    srp: { grid: Array.from(grid, v => (v - lo) / (hi - lo || 1)), peaks: pk.slice(0, nsrc).sort((a, b) => a - b) },
    motor: { fan: ds(ms.fan), neck: ds(ms.neck), sh: ds(ms.sh), walk: ds(ms.walk) },
    talk: { man: [0.3, 0.3 + voices.male.length / FS], woman: [2.6, 2.6 + voices.female.length / FS] },
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
