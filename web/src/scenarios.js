// Scene Simulator: scenario definitions and ambient-noise generators (Home, Factory, Hospital, Automobile).
// Concatenated AFTER engine.js in one scope; uses its globals at call time only: FS, N, makeRng, bandnoise, tone.
//
// HONEST LIMITS: there is NO recorded ambience anywhere in this file. Every noise is synthesised from simple
// recipes (harmonic series, filtered noise, decaying resonances, periodic events, time-scrambled copies of the
// voice files). Realism is qualitative: each source has the right spectral shape and temporal pattern to be
// recognisable and to behave as a plausible interferer (tonal, impulsive, babble-like, moving), but levels,
// spectra and timing are NOT calibrated against real rooms, machines or cars.
//
// Contract: NOISE_GEN[gen](rng, p, voices) -> Float64Array(N), mono, finite, deterministic for a given rng seed.
// No placement and no relative-level scaling (the engine does that). Each output is normalised to unit RMS over
// the 5.5 s so the engine's dB offsets mean the same thing for every generator. Helpers are prefixed "sc".
"use strict";

// ---------------------------------------------------------------- helpers
function scZeros() { return new Float64Array(N); }
function scNormRms(x) {
  let e = 0; for (let i = 0; i < x.length; i++) e += x[i] * x[i];
  const r = Math.sqrt(e / x.length) || 1;
  for (let i = 0; i < x.length; i++) x[i] /= r;
  return x;
}
function scAdd(a, b, g = 1) { for (let i = 0; i < a.length; i++) a[i] += g * b[i]; return a; }
function scRms(x) { let e = 0; for (let i = 0; i < x.length; i++) e += x[i] * x[i]; return Math.sqrt(e / x.length); }
function scLp(x, fc) { const a = Math.exp(-2 * Math.PI * fc / FS), y = new Float64Array(x.length); let s = 0; for (let i = 0; i < x.length; i++) { s = a * s + (1 - a) * x[i]; y[i] = s; } return y; }
function scHp(x, fc) { const l = scLp(x, fc), y = new Float64Array(x.length); for (let i = 0; i < x.length; i++) y[i] = x[i] - l[i]; return y; }
// smooth slow random modulation in [1-depth, 1+depth] with correlation rate ~ rate Hz
function scWander(rng, rate, depth) {
  const m = Math.ceil(N / FS * rate * 4) + 4, pts = Array.from({ length: m }, () => rng.u() * 2 - 1), out = scZeros(), step = FS / (rate * 4);
  for (let i = 0; i < N; i++) { const f = i / step, k = Math.floor(f), t = f - k, w = 0.5 - 0.5 * Math.cos(Math.PI * t); out[i] = 1 + depth * (pts[k] * (1 - w) + pts[k + 1] * w); }
  return out;
}
// add a decaying set of resonances [[freq, amp, tau_s], ...] starting at sample s0
function scRing(out, s0, parts, len) {
  const L = len || Math.round(0.6 * FS);
  for (const [f, a, tau] of parts) {
    const ph = 0, w = 2 * Math.PI * f / FS;
    const n = Math.min(L, Math.round(tau * 8 * FS));
    for (let k = 0; k < n && s0 + k < N; k++) if (s0 + k >= 0) out[s0 + k] += a * Math.sin(w * k + ph) * Math.exp(-k / FS / tau);
  }
}
// add a pre-made burst (noise) with exponential decay tau at s0
function scBurst(out, s0, burst, amp, tau, attack = 0.0005) {
  for (let k = 0; k < burst.length && s0 + k < N; k++) {
    const t = k / FS;
    if (s0 + k >= 0) out[s0 + k] += amp * burst[k] * Math.exp(-t / tau) * Math.min(1, t / attack);
  }
}
// gated tone: freq, on/off times with raised-cosine ramps
function scGate(out, t0, dur, f, harm, amp, ramp = 0.006) {
  const s0 = Math.round(t0 * FS), n = Math.round(dur * FS);
  for (let k = 0; k < n && s0 + k < N; k++) {
    if (s0 + k < 0) continue;
    const t = k / FS, e = Math.min(1, t / ramp, (dur - t) / ramp), g = 0.5 - 0.5 * Math.cos(Math.PI * Math.max(0, e));
    let s = 0; for (const [m, a] of harm) s += a * Math.sin(2 * Math.PI * f * m * t);
    out[s0 + k] += amp * g * s;
  }
}
function scResample(x, ratio) {
  const n = Math.max(2, Math.floor((x.length - 1) / ratio)), y = new Float64Array(n);
  for (let i = 0; i < n; i++) { const f = i * ratio, k = Math.floor(f), t = f - k; y[i] = x[k] * (1 - t) + x[k + 1] * t; }
  return y;
}
function scFade(i, n, f) { return Math.min(1, i / f, (n - 1 - i) / f); }

// Speech-like fallback when no voice files are supplied: glottal pulses through formant resonances, syllable envelope.
function scFakeVoice(rng, len, f0) {
  const out = new Float64Array(len), forms = [[600, 0.97], [1500, 0.96], [2600, 0.95]];
  const st = forms.map(() => [0, 0]);
  let ph = 0, syl = 0, env = 0, f1 = 500;
  for (let i = 0; i < len; i++) {
    if (i >= syl) { syl = i + Math.round((0.12 + 0.18 * rng.u()) * FS); env = rng.u() < 0.2 ? 0 : 0.4 + 0.6 * rng.u(); f1 = 350 + 600 * rng.u(); forms[0][0] = f1; }
    ph += f0 * (1 + 0.1 * Math.sin(i / FS * 5)) / FS; if (ph >= 1) ph -= 1;
    let x = (ph < 0.1 ? 1 - ph * 10 : 0) + 0.02 * rng.g(), y = 0;
    forms.forEach(([f, r], j) => { const w = 2 * Math.PI * f / FS, s = st[j], v = x + 2 * r * Math.cos(w) * s[0] - r * r * s[1]; s[1] = s[0]; s[0] = v; y += v * (1 - 0.3 * j); });
    out[i] = y * env;
  }
  return out;
}

// Babble: nTalk overlapping talkers, each = chopped, time-scrambled, pitch-shifted (resampled) copies of the voice files,
// with random pauses. segLo..segHi = chunk length in s (short = unintelligible babble, long = near-speech announcement).
function scBabble(rng, voices, nTalk, segLo, segHi, pitchLo, pitchHi, gapProb) {
  const out = scZeros();
  for (let t = 0; t < nTalk; t++) {
    const ratio = pitchLo + (pitchHi - pitchLo) * rng.u();
    let src;
    if (voices && (voices.male || voices.female)) {
      const pool = [voices.male, voices.female].filter(Boolean);
      src = scResample(pool[Math.floor(rng.u() * pool.length)], ratio);
    } else src = scFakeVoice(rng, 3 * FS, 110 * ratio * (rng.u() < 0.5 ? 1 : 1.8));
    const tk = scZeros();
    let pos = Math.round(rng.u() * 0.3 * FS);
    while (pos < N) {
      const len = Math.round((segLo + (segHi - segLo) * rng.u()) * FS);
      if (rng.u() > gapProb) {
        const off = Math.floor(rng.u() * Math.max(1, src.length - len));
        const xf = Math.round(0.02 * FS);
        for (let k = 0; k < len && pos + k < N; k++) tk[pos + k] += src[(off + k) % src.length] * (0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, k / xf, (len - 1 - k) / xf)));
      }
      pos += len;
    }
    scAdd(out, scNormRms(tk), 1);
  }
  return out;
}

// Simple music: chord progression, decaying plucked notes with harmonics, bass line, optional drums. Synthesised toy music.
function scMusic(rng, bpm, drums) {
  const out = scZeros(), beat = 60 / bpm, roots = [220, 174.6, 261.6, 196], hz = r => r;
  const nb = Math.ceil(N / FS / beat) + 1;
  const rootSel = Math.floor(rng.u() * 4);
  for (let b = 0; b < nb; b++) {
    const root = roots[(rootSel + Math.floor(b / 4)) % 4], t0 = b * beat, s0 = Math.round(t0 * FS);
    const notes = [root, root * 1.25, root * 1.5, root * 2];
    const f = hz(notes[(b * 3 + (b >> 2)) % 4] * (rng.u() < 0.2 ? 2 : 1));
    scRing(out, s0, [[f, 0.5, 0.25], [2 * f, 0.25, 0.18], [3 * f, 0.12, 0.12], [4 * f, 0.06, 0.08]], Math.round(beat * 2 * FS));
    if (b % 2 === 0) scRing(out, s0, [[root / 2, 0.8, 0.35], [root, 0.3, 0.2]], Math.round(beat * 2 * FS));
    if (b % 4 === 0) for (const nf of [root, root * 1.25, root * 1.5]) scRing(out, s0, [[nf, 0.15, 0.6]], Math.round(beat * 4 * FS));
  }
  if (drums) {
    const hat = bandnoise(5000, 7800, Math.round(0.05 * FS), rng), kick = new Float64Array(Math.round(0.2 * FS));
    for (let k = 0; k < kick.length; k++) { const t = k / FS; kick[k] = Math.sin(2 * Math.PI * (50 + 80 * Math.exp(-t / 0.03)) * t) * Math.exp(-t / 0.07); }
    for (let b = 0; b < nb * 2; b++) {
      const s0 = Math.round(b * beat / 2 * FS);
      scBurst(out, s0, hat, b % 2 ? 0.25 : 0.1, 0.012);
      if (b % 4 === 0) for (let k = 0; k < kick.length && s0 + k < N; k++) out[s0 + k] += 1.2 * kick[k];
    }
  }
  return out;
}

// Robot-like machine: servo whine whose pitch follows a random speed profile, plus grinding and metallic footsteps.
function scRobot(rng, base, span, stepPeriod) {
  const speed = scZeros();
  let t = 0.2 * rng.u();
  while (t < DUR_SC()) { const d = 0.5 + 0.9 * rng.u(), amp = 0.4 + 0.6 * rng.u(); for (let i = Math.round(t * FS); i < Math.min(N, Math.round((t + d) * FS)); i++) speed[i] = amp * Math.sin(Math.PI * (i / FS - t) / d); t += d + 0.15 * rng.u(); }
  const whine = tone(speed.map(s => base + span * s), [[1, 1.0], [2, 0.6], [3, 0.3], [5, 0.15]], rng);
  const grind = bandnoise(1500, 6000, N, rng);
  const out = scZeros();
  for (let i = 0; i < N; i++) out[i] = (whine[i] + 0.7 * grind[i] * (0.5 + 0.5 * Math.sin(2 * Math.PI * 37 * i / FS))) * speed[i];
  const K = Math.round(0.2 * FS);
  for (let s = Math.round(rng.u() * stepPeriod * FS); s < N; s += Math.round(stepPeriod * FS * (0.95 + 0.1 * rng.u()))) {
    const click = bandnoise(1500, 7000, K, rng), a = 3 * (0.8 + 0.4 * rng.u());
    for (let k = 0; k < K && s + k < N; k++) { const tk = k / FS; out[s + k] += a * (Math.sin(2 * Math.PI * 90 * tk) * Math.exp(-tk / 0.04) + 0.5 * click[k] * Math.exp(-tk / 0.006)); }
  }
  return out;
}
function DUR_SC() { return N / FS; }

// ---------------------------------------------------------------- generators
const NOISE_GEN = {
  // HOME ---------------------------------------------------------------------------------------------------
  // TV: 3-talker babble (voice files, scrambled/pitch-shifted) 300-5000 Hz over a quiet synthesised toy-music bed. Approximate.
  tv(rng, p, voices) {
    const sp = scZeros(), bab = scBabble(rng, voices, 3, 0.25, 0.7, 0.85, 1.25, 0.15);
    const mus = scMusic(rng, 96 + Math.floor(rng.u() * 20), true);
    scAdd(sp, scNormRms(scHp(scLp(bab, 5000), 250)), 1); scAdd(sp, scNormRms(scLp(mus, 7000)), 0.5);
    return scNormRms(sp);
  },
  // Fridge: 50 Hz mains harmonics (50/100/150/200) plus a compressor that cycles on for ~3 s (adds 100/300 Hz motor tones,
  // low-frequency rumble and slight rattle). Synthesised, approximate.
  fridge(rng) {
    const out = tone(new Float64Array(N).fill(50), [[1, 0.5], [2, 1.0], [3, 0.35], [4, 0.2]], rng);
    const on0 = 0.4 + 0.8 * rng.u(), on1 = on0 + 2.8 + rng.u(), motor = tone(new Float64Array(N).fill(100), [[1, 0.8], [3, 0.4], [5, 0.2]], rng), rum = bandnoise(60, 500, N, rng), rat = bandnoise(300, 1800, N, rng);
    for (let i = 0; i < N; i++) { const t = i / FS, g = Math.min(1, Math.max(0, (t - on0) / 0.25), Math.max(0, (on1 - t) / 0.4)); out[i] = 0.4 * out[i] + g * (motor[i] + 1.2 * rum[i] + 0.25 * rat[i] * (0.6 + 0.4 * Math.sin(2 * Math.PI * 11 * t))); }
    return scNormRms(out);
  },
  // Kitchen: running water (steady 1.5-7 kHz hiss with slow wander and droplets) plus 9-12 clatter events (pans/dishes: 2-5 kHz ringing + click). Synthesised.
  kitchen(rng) {
    const out = scZeros(), w = bandnoise(1500, 7000, N, rng), wm = scWander(rng, 3, 0.25), lo = bandnoise(300, 1200, N, rng);
    for (let i = 0; i < N; i++) out[i] = (w[i] + 0.3 * lo[i]) * wm[i] * 0.35;
    for (let d = 0; d < 14; d++) { const s0 = Math.floor(rng.u() * (N - 800)), f = 2500 + 2000 * rng.u(); scRing(out, s0, [[f, 0.25, 0.006]], 600); }
    const n = 9 + Math.floor(rng.u() * 4);
    for (let e = 0; e < n; e++) {
      const s0 = Math.floor(((e % 3) * 0.3 + rng.u() * 1.2 + Math.floor(e / 3) * 1.4) * FS), f = 800 + 3200 * rng.u(), a = 0.6 + 1.2 * rng.u();
      scRing(out, s0, [[f, a, 0.02 + 0.06 * rng.u()], [f * 2.76, a * 0.5, 0.02], [f * 5.4, a * 0.25, 0.012]], Math.round(0.4 * FS));
      scBurst(out, s0, bandnoise(1500, 7000, 400, rng), a, 0.003);
    }
    return scNormRms(out);
  },
  // Vacuum cleaner: motor harmonics around 250-300 Hz (1,2,3,4,6) with load wander plus loud 300-6000 Hz airflow noise. Synthesised.
  vacuum(rng) {
    const wan = scWander(rng, 1, 0.04), f0 = new Float64Array(N);
    for (let i = 0; i < N; i++) f0[i] = 270 * wan[i] * (1 + 0.08 * Math.min(1, i / FS / 0.6));
    const m = tone(f0, [[1, 1.0], [2, 0.7], [3, 0.5], [4, 0.35], [6, 0.2], [8, 0.1]], rng), a = bandnoise(300, 6000, N, rng), a2 = bandnoise(2000, 7500, N, rng);
    const out = scZeros(); for (let i = 0; i < N; i++) out[i] = 0.6 * m[i] + a[i] + 0.4 * a2[i];
    return scNormRms(out);
  },
  // Door knocks: 2 groups of 3 knocks (~0.22 s apart); each knock = wood thump (150/320/600 Hz, ~25 ms) + short click. Synthesised.
  knocks(rng) {
    const out = scZeros(), cl = bandnoise(800, 5000, 300, rng);
    const g0 = 0.6 + 0.8 * rng.u(), g1 = g0 + 2.2 + rng.u();
    for (const g of [g0, g1]) for (let k = 0; k < 3; k++) {
      const s0 = Math.round((g + k * (0.2 + 0.05 * rng.u())) * FS), a = 0.8 + 0.4 * rng.u();
      scRing(out, s0, [[150, a, 0.03], [320, 0.6 * a, 0.02], [600, 0.3 * a, 0.012]], 2000);
      scBurst(out, s0, cl, 0.5 * a, 0.002);
    }
    return scNormRms(out);
  },
  // Air-conditioner: 100-3000 Hz fan roar with slow wander, 2-8 kHz air hiss, weak 50 Hz compressor hum. Synthesised.
  aircon(rng) {
    const a = bandnoise(100, 3000, N, rng), b = bandnoise(2000, 8000, N, rng), h = tone(new Float64Array(N).fill(50), [[1, 1], [2, 0.5]], rng), m = scWander(rng, 0.5, 0.12);
    const out = scZeros(); for (let i = 0; i < N; i++) out[i] = (a[i] + 0.4 * b[i] + 0.15 * h[i]) * m[i];
    return scNormRms(out);
  },

  // FACTORY ------------------------------------------------------------------------------------------------
  // Machine hum: 100 Hz mains-rectified harmonic series (1,2,3,4,6,8) + slowly drifting 1.1-1.3 kHz drive whine + broadband 200-4000 Hz machinery noise. Synthesised.
  machine_hum(rng) {
    const wan = scWander(rng, 0.4, 0.02), f0 = new Float64Array(N).fill(100), fw = new Float64Array(N);
    for (let i = 0; i < N; i++) fw[i] = 1200 * wan[i] * wan[i];
    const h = tone(f0, [[1, 1.0], [2, 0.6], [3, 0.5], [4, 0.3], [6, 0.25], [8, 0.15]], rng), w = tone(fw, [[1, 0.5], [2, 0.25], [3, 0.1]], rng), b = bandnoise(200, 4000, N, rng);
    const out = scZeros(); for (let i = 0; i < N; i++) out[i] = h[i] + w[i] + 0.8 * b[i];
    return scNormRms(out);
  },
  // Stamping press: one bang every 1.3-1.8 s, each = low thump (60 Hz) + 100-6000 Hz impact noise (~30 ms) + steel ring-down
  // (110/260/540/1100/2300 Hz, 0.1-0.4 s) preceded by a short hydraulic hiss. Synthesised.
  press(rng) {
    const out = scZeros(), imp = bandnoise(100, 6000, Math.round(0.4 * FS), rng), hiss = bandnoise(1000, 6000, Math.round(0.3 * FS), rng);
    for (let t = 0.2 + 0.8 * rng.u(); t < 5.3; t += 1.3 + 0.5 * rng.u()) {
      const s0 = Math.round(t * FS), a = 0.85 + 0.3 * rng.u();
      for (let k = 0; k < hiss.length; k++) if (s0 - hiss.length + k >= 0) out[s0 - hiss.length + k] += 0.15 * hiss[k] * (k / hiss.length);
      scBurst(out, s0, imp, 2.0 * a, 0.03);
      scRing(out, s0, [[60, 2.5 * a, 0.06], [110, 1.2 * a, 0.3], [260, 0.9 * a, 0.2], [540, 0.6 * a, 0.15], [1100, 0.35 * a, 0.12], [2300, 0.2 * a, 0.1]], Math.round(1.2 * FS));
    }
    return scNormRms(out);
  },
  // Compressed-air hiss: 3-4 bursts of 3-7.8 kHz noise (0.25-0.7 s, fast attack, soft release) over a faint leak. Synthesised.
  airhiss(rng) {
    const out = scZeros(), h = bandnoise(3000, 7800, N, rng), lk = bandnoise(2500, 7500, N, rng), env = scZeros();
    let t = 0.2 + 0.6 * rng.u();
    const nb = 3 + Math.floor(rng.u() * 2);
    for (let b = 0; b < nb && t < 5.2; b++) {
      const d = 0.25 + 0.45 * rng.u(), a = 0.6 + 0.4 * rng.u();
      for (let i = Math.round(t * FS); i < Math.min(N, Math.round((t + d + 0.1) * FS)); i++) { const x = i / FS - t; env[i] = a * Math.min(1, x / 0.012) * (x < d ? 1 : Math.exp(-(x - d) / 0.04)) * (1 + 0.15 * Math.sin(2 * Math.PI * 23 * x)); }
      t += d + 0.5 + 0.9 * rng.u();
    }
    for (let i = 0; i < N; i++) out[i] = h[i] * env[i] + 0.04 * lk[i];
    return scNormRms(out);
  },
  // AGV reverse beeper: 1 kHz (+2 kHz) beep, 0.5 s on / 0.5 s off with 6 ms ramps, over soft 200-900 Hz drive whirr. Synthesised.
  agv_beeper(rng) {
    const out = scZeros(), ph = rng.u();
    for (let t = -ph * 1.0; t < 5.5; t += 1.0) scGate(out, t, 0.5, 1000, [[1, 1.0], [2, 0.35], [3, 0.12]], 1);
    const w = bandnoise(200, 900, N, rng); for (let i = 0; i < N; i++) out[i] += 0.12 * w[i];
    return scNormRms(out);
  },
  // Walking robot A (the "other robots" in the factory): servo whine 700-1400 Hz following random move profile + grind + metallic steps every ~0.62 s. Synthesised.
  robot_a(rng) { return scNormRms(scRobot(rng, 700, 700, 0.62)); },
  // Walking robot B: same recipe, higher whine (1100-2000 Hz), faster steps (~0.5 s). Synthesised.
  robot_b(rng) { return scNormRms(scRobot(rng, 1100, 900, 0.5)); },
  // Conveyor: 40-300 Hz rumble modulated at roller rate (~17 Hz), 500-3000 Hz belt noise, belt-joint clacks every ~0.45 s, one package thump. Synthesised.
  conveyor(rng) {
    const r = bandnoise(40, 300, N, rng), b = bandnoise(500, 3000, N, rng), out = scZeros(), cl = bandnoise(1000, 6000, 300, rng);
    for (let i = 0; i < N; i++) out[i] = r[i] * (1 + 0.35 * Math.sin(2 * Math.PI * 17 * i / FS)) + 0.3 * b[i];
    for (let t = 0.1 + 0.4 * rng.u(); t < 5.4; t += 0.45 + 0.04 * rng.g()) { const s0 = Math.round(t * FS); scBurst(out, s0, cl, 1.0, 0.006); scRing(out, s0, [[420, 0.8, 0.012]], 1500); }
    scRing(out, Math.round((1 + 3 * rng.u()) * FS), [[90, 3, 0.07], [200, 1.5, 0.05]], 6000);
    return scNormRms(out);
  },

  // HOSPITAL -----------------------------------------------------------------------------------------------
  // Patient monitor: 880 Hz (+1760) 110 ms beep about every 0.86 s (heart rate ~70) with small jitter and a quiet 50 Hz hum. Synthesised.
  monitor(rng) {
    const out = scZeros();
    for (let t = rng.u() * 0.86; t < 5.5; t += 0.86 + 0.01 * rng.g()) scGate(out, t, 0.11, 880, [[1, 1.0], [2, 0.25]], 1, 0.008);
    const h = tone(new Float64Array(N).fill(50), [[1, 1]], rng); scAdd(out, h, 0.04);
    return scNormRms(out);
  },
  // IV-pump alarm (second bedside device): 3-note "ding-ding-dong" (1320/1320/990 Hz, bell-like decay) repeated every ~1.9 s. Synthesised.
  ivpump(rng) {
    const out = scZeros();
    for (let t = 0.1 + 0.8 * rng.u(); t < 5.4; t += 1.9) [[0, 1320], [0.22, 1320], [0.44, 990]].forEach(([dt, f]) => scRing(out, Math.round((t + dt) * FS), [[f, 1, 0.09], [2 * f, 0.25, 0.05]], 4000));
    return scNormRms(out);
  },
  // Ventilator: 3 s breath cycle: ~1 s inspiratory hiss (200-2500 Hz, smooth rise/fall), pause, ~1.2 s exhalation (150-1200 Hz decaying), valve click at each phase + 120 Hz blower hum. Synthesised.
  ventilator(rng) {
    const ins = bandnoise(200, 2500, N, rng), exh = bandnoise(150, 1200, N, rng), out = scZeros(), hum = tone(new Float64Array(N).fill(120), [[1, 1], [2, 0.4]], rng), ph = rng.u() * 3, cl = bandnoise(1000, 5000, 200, rng);
    for (let i = 0; i < N; i++) {
      const t = (i / FS + ph) % 3;
      let g = 0;
      if (t < 1.0) g = Math.sin(Math.PI * t / 1.0) ** 2; else if (t >= 1.3 && t < 2.5) { const x = (t - 1.3) / 1.2; out[i] = exh[i] * 0.8 * Math.exp(-3 * x) * Math.min(1, x * 20); }
      out[i] += ins[i] * g * 0.9 + 0.12 * hum[i];
    }
    for (let c = -ph; c < 5.5; c += 1.5) if (c >= 0) scBurst(out, Math.round(c * FS), cl, 0.7, 0.003);   // valve clicks at phase changes (approx.)
    return scNormRms(out);
  },
  // HVAC: 60-800 Hz duct rumble, low-passed 800-5000 Hz air noise, 120 Hz blower tone, +-10 % slow wander. Synthesised.
  hvac(rng) {
    const a = bandnoise(60, 800, N, rng), b = scLp(bandnoise(800, 5000, N, rng), 2500), h = tone(new Float64Array(N).fill(120), [[1, 1], [2, 0.3]], rng), m = scWander(rng, 0.3, 0.1);
    const out = scZeros(); for (let i = 0; i < N; i++) out[i] = (a[i] + 0.6 * b[i] * 3 + 0.15 * h[i]) * m[i];
    return scNormRms(out);
  },
  // PA: 2-note bell chime (E5 then C5, inharmonic partials, ~0.8 s ring) then a muffled 300-3400 Hz "announcement" made of longer (0.6-1.2 s)
  // scrambled voice-file chunks, with a faint amplifier hum. Not intelligible speech. Synthesised.
  pa(rng, p, voices) {
    const out = scZeros(), bell = f => [[f, 1, 0.5], [f * 2.76, 0.4, 0.3], [f * 5.4, 0.15, 0.15]];
    scRing(out, Math.round(0.25 * FS), bell(659), Math.round(1.2 * FS)); scRing(out, Math.round(0.85 * FS), bell(523), Math.round(1.5 * FS));
    const bab = scNormRms(scHp(scLp(scBabble(rng, voices, 1, 0.6, 1.2, 0.95, 1.05, 0.1), 3400), 300));
    const s0 = Math.round(1.9 * FS), hum = tone(new Float64Array(N).fill(100), [[1, 1]], rng);
    for (let i = s0; i < N; i++) out[i] += 1.0 * bab[i] * scFade(i - s0, N - s0, 0.1 * FS);
    scAdd(out, hum, 0.03);
    return scNormRms(out);
  },
  // Trolley: wheel rumble 150-2500 Hz modulated at wheel rotation (~8 Hz), floor-joint clacks every ~0.35 s, a squeaking wheel (2.2-2.6 kHz glide), speed envelope rising then falling. Synthesised.
  trolley(rng) {
    const r = bandnoise(150, 2500, N, rng), out = scZeros(), cl = bandnoise(500, 4000, 200, rng), sq = scZeros(), sq0 = 1.0 + 2 * rng.u();
    for (let i = 0; i < N; i++) { const t = i / FS, sp = Math.sin(Math.PI * Math.min(1, Math.max(0, t / 5.2))) ** 0.7; out[i] = r[i] * (1 + 0.6 * Math.sin(2 * Math.PI * 8 * t * (0.5 + sp))) * sp; }
    for (let t = 0.2; t < 5.3; t += 0.35) { const sp = Math.sin(Math.PI * t / 5.4); scBurst(out, Math.round(t * FS), cl, 1.5 * sp, 0.008); }
    let ph = 0; for (let i = 0; i < N; i++) { const t = i / FS - sq0; if (t < 0 || t > 1.2) continue; ph += 2 * Math.PI * (2200 + 400 * t) / FS; sq[i] = 0.5 * Math.sin(ph) * Math.sin(Math.PI * t / 1.2) * (0.7 + 0.3 * Math.sin(2 * Math.PI * 14 * t)); }
    scAdd(out, sq, 1);
    return scNormRms(out);
  },
  // Distant chatter: 5-talker babble from the voice files (0.15-0.45 s chunks, pitch 0.8-1.4), low-passed 3.5 kHz for distance. Synthesised babble, not speech.
  chatter(rng, p, voices) { return scNormRms(scLp(scHp(scBabble(rng, voices, 5, 0.15, 0.45, 0.8, 1.4, 0.35), 200), 3500)); },

  // AUTOMOBILE ---------------------------------------------------------------------------------------------
  // Engine: 4-cylinder firing frequency = 2 x rpm/60, rpm ramps 900 -> 1500 over the clip with jitter; 12-harmonic series with 1/k rolloff plus 50-600 Hz mechanical rumble. Synthesised.
  engine(rng) {
    const f = new Float64Array(N), j = scWander(rng, 4, 0.01), H = [];
    for (let k = 1; k <= 12; k++) H.push([k, 1 / k ** 0.8 * (k % 2 ? 1 : 1.2)]);
    for (let i = 0; i < N; i++) f[i] = 2 * (900 + 600 * (i / N) ** 1.2) / 60 * j[i];
    const h = tone(f, H, rng), r = bandnoise(50, 600, N, rng), out = scZeros();
    for (let i = 0; i < N; i++) out[i] = h[i] + 0.6 * r[i];
    return scNormRms(out);
  },
  // Road/tyre noise: 30-250 Hz rumble + 250-1500 Hz tread noise + 800-4000 Hz hiss with slow level wander. Synthesised.
  road(rng) {
    const a = bandnoise(30, 250, N, rng), b = bandnoise(250, 1500, N, rng), c = bandnoise(800, 4000, N, rng), m = scWander(rng, 0.7, 0.15), out = scZeros();
    for (let i = 0; i < N; i++) out[i] = (a[i] + 0.6 * b[i] + 0.25 * c[i]) * m[i];
    return scNormRms(out);
  },
  // Wind: 100-1500 Hz turbulence gusting at 0.4-0.8 Hz plus 2-6 kHz whistle-hiss riding the same gusts. Synthesised.
  wind(rng) {
    const a = bandnoise(100, 1500, N, rng), b = bandnoise(2000, 6000, N, rng), m = scWander(rng, 0.6, 0.45), out = scZeros();
    for (let i = 0; i < N; i++) { const g = Math.max(0.05, m[i]); out[i] = (a[i] + 0.35 * b[i] * g) * g * g; }
    return scNormRms(out);
  },
  // HVAC blower: 7-blade fan at ~3000 rpm -> 350 Hz blade-pass tone (+harmonics) over 200-5000 Hz air noise and a 2-8 kHz vent hiss. Synthesised.
  blower(rng) {
    const t = tone(new Float64Array(N).fill(350), [[1, 1], [2, 0.5], [3, 0.3], [4, 0.15]], rng), a = bandnoise(200, 5000, N, rng), b = bandnoise(2000, 8000, N, rng), out = scZeros();
    for (let i = 0; i < N; i++) out[i] = 0.5 * t[i] + a[i] + 0.3 * b[i];
    return scNormRms(out);
  },
  // Turn-signal relay: tick (1.3 kHz ring) and tock (0.9 kHz ring) at 1.6 Hz, each a 4 ms noise click + 10 ms resonance. Synthesised.
  indicator(rng) {
    const out = scZeros(), cl = bandnoise(800, 5000, 200, rng);
    for (let t = 0.1 + 0.3 * rng.u(); t < 5.4; t += 0.625) {
      const s0 = Math.round(t * FS), s1 = Math.round((t + 0.3125) * FS);
      scBurst(out, s0, cl, 1, 0.004); scRing(out, s0, [[1300, 0.8, 0.01]], 600);
      scBurst(out, s1, cl, 0.7, 0.004); scRing(out, s1, [[900, 0.6, 0.012]], 600);
    }
    return scNormRms(out);
  },
  // Road bumps: 2-3 events, each = body thump (55/110 Hz, 0.1-0.15 s) + 200-1200 Hz suspension rattle, repeated ~0.12 s later for the rear axle. Synthesised.
  bumps(rng) {
    const out = scZeros(), rat = bandnoise(200, 1200, Math.round(0.3 * FS), rng), nb = 2 + Math.floor(rng.u() * 2);
    for (let b = 0; b < nb; b++) {
      const t = 0.5 + b * 1.7 + 0.6 * rng.u(), a = 0.7 + 0.6 * rng.u();
      [[0, 1], [0.12, 0.7]].forEach(([dt, g]) => { const s0 = Math.round((t + dt) * FS); scRing(out, s0, [[55, 2 * a * g, 0.1], [110, a * g, 0.08]], 4000); scBurst(out, s0, rat, 1.2 * a * g, 0.05); });
    }
    return scNormRms(out);
  },
  // Radio: synthesised toy music (chord progression, bass, hi-hat/kick at 100-130 bpm) band-limited 80-7000 Hz, as through a car speaker. Not recorded music.
  radio(rng) { return scNormRms(scHp(scLp(scMusic(rng, 100 + Math.floor(rng.u() * 30), true), 7000), 80)); },
};

// ---------------------------------------------------------------- scenarios
const SCENARIO_ORDER = ["home", "factory", "hospital", "automobile"];

const scRobotDefaults = { fanOn: true, fanDb: -6, fanRpm: 4200, neckOn: true, neckDb: -4, shouldersOn: true, shouldersDb: -8, footstepsOn: false, footstepsDb: -2, clicksOn: true, clicksDb: -10, humOn: true, humDb: -25 };
const scN = (id, label, gen, az, el, dist, db, on, path) => ({ id, label, gen, az, el, dist, db, on, path: path || null });
const scS = (id, voice, az, el, dist, db, start, target) => ({ id, voice, az, el, dist, db, start, target });

const SCENARIOS = {
  home: {
    label: "Home",
    desc: "Living room and kitchen, 5 x 4 x 2.6 m, soft furnishings: TV, fridge, kitchen clatter, a vacuum cleaner moving past, door knocks and an air-conditioner.",
    params: Object.assign({
      scenario: "home", roomL: 5, roomW: 4, roomH: 2.6, rt60: 0.45, damping: 0.5, roomDb: 30,
      micCount: 8, arrayShape: "ring", ringGap: 8, radius: 5, arrayH: 1.3, arrayX: 2.5, arrayY: 2.0,
      speakers: [scS("s1", "male", 20, 5, 1.5, 0, 0.3, true), scS("s2", "female", 150, 0, 1.6, 0, 2.6, true)],
      noises: [
        scN("tv", "TV (talk + music)", "tv", 340, 10, 2.1, -8, true),
        scN("fridge", "Fridge hum + compressor", "fridge", 150, -10, 2.0, -14, true),
        scN("kitchen", "Kitchen clatter + water", "kitchen", 110, -5, 1.8, -10, true),
        scN("vacuum", "Vacuum cleaner (moves)", "vacuum", 200, -25, 2.0, -9, true, { az1: 300, el1: -20, dist1: 1.5 }),
        scN("knocks", "Door knocks", "knocks", 250, 5, 1.7, -8, true),
        scN("aircon", "Air-conditioner", "aircon", 60, 40, 1.2, -16, true),
      ],
    }, scRobotDefaults, { humDb: -25 }),
  },
  factory: {
    label: "Factory / Industry",
    desc: "Manufacturing hall, 20 x 15 x 7 m, hard and reverberant: mains hum and drive whine, a stamping press, compressed-air hiss, an AGV reversing beeper, two other robots walking around and a conveyor.",
    params: Object.assign({
      scenario: "factory", roomL: 20, roomW: 15, roomH: 7, rt60: 1.2, damping: 0.1, roomDb: 18,
      micCount: 8, arrayShape: "ring", ringGap: 8, radius: 5, arrayH: 1.5, arrayX: 10, arrayY: 7.5,
      speakers: [scS("s1", "male", 30, 0, 1.5, 0, 0.3, true), scS("s2", "female", 200, 0, 2.0, 0, 2.6, true)],
      noises: [
        scN("machine", "Machine hum + drive whine", "machine_hum", 90, 20, 6, -6, true),
        scN("press", "Stamping press", "press", 330, 10, 7, -3, true),
        scN("airhiss", "Compressed-air hiss", "airhiss", 250, 40, 4, -10, true),
        scN("agv", "AGV reverse beeper (moves)", "agv_beeper", 120, -5, 7, -8, true, { az1: 40, el1: -5, dist1: 6 }),
        scN("robot1", "Other robot 1 (moves)", "robot_a", 60, -5, 5, -9, true, { az1: 170, el1: -5, dist1: 3.5 }),
        scN("robot2", "Other robot 2 (moves)", "robot_b", 300, -5, 6, -9, true, { az1: 220, el1: -5, dist1: 4 }),
        scN("conveyor", "Conveyor rumble + clacks", "conveyor", 180, -10, 5, -9, true),
      ],
    }, scRobotDefaults, { fanDb: -4 }),
  },
  hospital: {
    label: "Hospital",
    desc: "Ward, 6 x 5 x 3 m, hard surfaces: patient-monitor beeps, an IV-pump alarm, ventilator, HVAC rumble, PA chime and announcement, a trolley rolling past and distant chatter.",
    params: Object.assign({
      scenario: "hospital", roomL: 6, roomW: 5, roomH: 3, rt60: 0.8, damping: 0.15, roomDb: 28,
      micCount: 8, arrayShape: "ring", ringGap: 8, radius: 5, arrayH: 1.5, arrayX: 3, arrayY: 2.5,
      speakers: [scS("s1", "female", 15, 0, 1.2, 0, 0.3, true), scS("s2", "male", 160, 0, 1.6, 0, 2.6, true)],
      noises: [
        scN("monitor", "Patient monitor beeps", "monitor", 330, 5, 2.0, -10, true),
        scN("ivpump", "IV-pump alarm (2nd device)", "ivpump", 40, 15, 1.8, -12, true),
        scN("ventilator", "Ventilator cycle", "ventilator", 300, -10, 1.8, -12, true),
        scN("hvac", "HVAC rumble", "hvac", 90, 55, 1.2, -14, true),
        scN("pa", "PA chime + announcement", "pa", 200, 50, 1.5, -10, true),
        scN("trolley", "Trolley wheels (moves)", "trolley", 250, -30, 2.2, -10, true, { az1: 330, el1: -30, dist1: 2.2 }),
        scN("chatter", "Distant chatter", "chatter", 120, 0, 2.5, -12, true),
      ],
    }, scRobotDefaults, {}),
  },
  automobile: {
    label: "Automobile",
    desc: "Car cabin, 2.7 x 1.6 x 1.2 m, very dry: array on the dashboard, driver and passenger as speakers; engine with rpm ramp, road, wind, HVAC blower, indicator relay, bumps and radio.",
    params: Object.assign({
      scenario: "automobile", roomL: 2.7, roomW: 1.6, roomH: 1.2, rt60: 0.12, damping: 0.7, roomDb: 22,
      micCount: 8, arrayShape: "ring", ringGap: 8, radius: 5, arrayH: 0.8, arrayX: 2.0, arrayY: 0.8,
      // driver (1.3, 0.4, 0.95) and passenger (1.3, 1.2, 0.95) relative to the dashboard array at (2.0, 0.8, 0.8)
      speakers: [scS("s1", "male", 210, 11, 0.82, 0, 0.3, true), scS("s2", "female", 150, 11, 0.82, 0, 2.6, true)],
      noises: [
        scN("engine", "Engine (rpm ramp)", "engine", 0, -25, 0.5, -8, true),
        scN("road", "Road / tyre", "road", 180, -40, 0.6, -9, true),
        scN("wind", "Wind", "wind", 270, 12, 0.6, -14, true),
        scN("blower", "HVAC blower", "blower", 330, -10, 0.5, -14, true),
        scN("indicator", "Indicator relay", "indicator", 230, 0, 0.6, -14, true),
        scN("bumps", "Road bumps", "bumps", 180, -35, 0.8, -10, true),
        scN("radio", "Radio", "radio", 90, -10, 0.6, -10, true),
      ],
    }, scRobotDefaults, { fanDb: -8, footstepsOn: false }),
  },
};
