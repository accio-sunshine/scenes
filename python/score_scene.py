"""
score_scene.py  -  independent Python check of a Scene Simulator scene.

The page builds its sound with a light, fast room model in the browser. This script takes the SAME dry sources and the
SAME placements, rebuilds the scene with pyroomacoustics (image-source room, as the original sim_conversation.py /
sim_8mic_robot_noise.py did) and scores it with the original Python STFT and MPDR beamformer code. If the page's scores
land close to these, the page's quick answers can be trusted for that scene.

Input: the page's zip ("Download all audio + scores") or a folder from `node web/tools/export_scene.js <scene> <dir>`.
  Both hold scene.json (resolved geometry and levels), dry/<source>.wav and the page's scores.
Run:   python python/score_scene.py scene_simulator_factory.zip [--json out.json]
Needs: pip install numpy scipy soundfile pyroomacoustics

What is the same as the page: dry signals (exported from it), positions (after any move inside the room), levels
(each source scaled so its energy at mic 1 is <db> relative to speaker 1, as the original scripts did), mic positions,
hum identical on every mic, moving sources (4 positions blended with the page's raised-cosine weights), the learned
robot-noise recipe (mixture + 3 x a second robot-only take).
What is different on purpose: the room (pyroomacoustics image sources up to the Sabine order, instead of the page's
3 bounces + statistical tail), the STFT (scipy) and the room noise (a fresh random draw at the same level).
"""
import argparse
import io
import json
import os
import sys
import time
import zipfile

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy.signal import fftconvolve, istft, stft

NFFT, HOP, C = 512, 128, 343.0
BANDS = [125, 250, 500, 1000, 2000, 4000, 8000]


# ---------------------------------------------------------------- input
class Scene:
    def __init__(self, path):
        if os.path.isdir(path):
            rd = lambda n: open(os.path.join(path, n), "rb").read()
            names = [os.path.relpath(os.path.join(dp, f), path).replace(os.sep, "/") for dp, _, fs in os.walk(path) for f in fs]
        else:
            z = zipfile.ZipFile(path)
            rd, names = z.read, z.namelist()
        if "scene.json" not in names:
            sys.exit(f"{path}: no scene.json. Download the zip again from the current page (older zips lack it).")
        self.geo = json.loads(rd("scene.json"))
        self.dry = {}
        for n in names:
            if n.startswith("dry/") and n.endswith(".wav"):
                x, fs = sf.read(io.BytesIO(rd(n)), dtype="float64")
                assert fs == self.geo["fs"], f"{n}: {fs} Hz"
                self.dry[n[4:-4]] = x
        self.page = json.loads(rd("page_scores.json")) if "page_scores.json" in names else None


# ---------------------------------------------------------------- room (pyroomacoustics)
def absorption(rt60, room_dim):
    """pyroomacoustics' Sabine inversion; when the RT60 is too short for the room (absorption would exceed 1), cap at
    0.99 like the page does instead of failing."""
    try:
        return pra.inverse_sabine(rt60, room_dim)
    except ValueError:
        L, W, H = room_dim
        a = min(0.99, 24 * np.log(10) * L * W * H / (C * 2 * (L * W + L * H + W * H) * rt60))
        return a, 1


def make_room(geo):
    room_dim, fs = geo["room"], geo["fs"]
    rt60, rt60_hf, damping = geo["rt60"], geo["rt60Hf"], geo["damping"]
    if damping <= 0:
        e_abs, max_order = absorption(rt60, room_dim)
        mat = pra.Material(e_abs)
    else:   # page: low band keeps rt60, high band (> ~2.5 kHz) gets rt60Hf, crossover 1.5-2.5 kHz
        a_lo, max_order = absorption(rt60, room_dim)
        a_hi, _ = absorption(rt60_hf, room_dim)
        coeffs = [a_lo if f <= 1000 else a_hi if f >= 4000 else 0.5 * (a_lo + a_hi) for f in BANDS]
        mat = pra.Material({"coeffs": coeffs, "center_freqs": BANDS})
    room = pra.ShoeBox(room_dim, fs=fs, materials=mat, max_order=max_order, air_absorption=False)
    room.add_microphone_array(pra.MicrophoneArray(np.array(geo["mics"]).T, fs))
    return room, max_order


def rirs_for(geo, positions):
    """{position tuple: list of M RIRs}; one pyroomacoustics run for all positions."""
    room, order = make_room(geo)
    uniq = list(dict.fromkeys(tuple(p) for p in positions))
    for p in uniq:
        room.add_source(list(p))
    room.compute_rir()
    return {p: [room.rir[m][s] for m in range(len(geo["mics"]))] for s, p in enumerate(uniq)}, order


def seg_weights(n):
    """The page's raised-cosine partition of unity over 4 positions centred at 0, n/3, 2n/3, n."""
    wd, i = n / 3, np.arange(n)
    return [np.where(np.abs(i - j * wd) < wd, 0.5 + 0.5 * np.cos(np.pi * np.abs(i - j * wd) / wd), 0.0) for j in range(4)]


def convolve(sig, rirs, n):
    return np.stack([fftconvolve(sig, h)[:n] for h in rirs])


# ---------------------------------------------------------------- original Python processing (sim_8mic_robot_noise.py)
def to_stft(x, fs):
    return stft(x, fs=fs, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[2]


def to_time(X, fs, n):
    return istft(X, fs=fs, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[1][:n]


def steering(rel, az, el, fs):
    f = np.arange(NFFT // 2 + 1) * fs / NFFT
    a, e = np.radians(az), np.radians(el)
    u = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    return np.exp(2j * np.pi * f[:, None] * (rel @ u)[None, :] / C)


def mvdr(frames, d, load=1e-3):
    M = d.shape[1]
    w = np.zeros_like(d)
    for f in range(d.shape[0]):
        Xf = frames[:, f, :]
        R = Xf @ Xf.conj().T / Xf.shape[1]
        R += load * np.trace(R).real / M * np.eye(M) + 1e-12 * np.eye(M)
        Rd = np.linalg.solve(R, d[f])
        w[f] = Rd / (d[f].conj() @ Rd)
    return w


def apply(w, X):
    return np.einsum("fm,mft->ft", w.conj(), X)


def power(x):
    return np.mean(np.abs(x) ** 2)


def db(a, b):
    return 10 * np.log10(power(a) / power(b))


# ---------------------------------------------------------------- scene
def score(sc, seed=0, wav_dir=None):
    """Scores (and, with wav_dir, the audio: mic1.wav and <speaker>_<beam>.wav, one gain for all like the originals)."""
    geo, dry, n, fs = sc.geo, sc.dry, sc.geo["n"], sc.geo["fs"]
    M = len(geo["mics"])
    rel = np.array(geo["mics"]) - np.array(geo["centre"])
    t0 = time.time()
    rir, order = rirs_for(geo, [p for s in geo["sources"] for p in s["positions"]])
    t_rir = time.time() - t0
    sw = seg_weights(n)

    def wet(sid, src):
        sig = dry[sid]
        if src.get("sameOnAllMics"):
            return np.tile(sig, (M, 1))
        pos = [tuple(p) for p in src["positions"]]
        if len(pos) == 1:
            return convolve(sig, rir[pos[0]], n)
        return sum(convolve(sig * w, rir[p], n) for w, p in zip(sw, pos))

    srcs = geo["sources"]
    ref = None
    comp, take2 = {}, {}
    for s in srcs:                               # speaker 1 first: it sets the reference level
        y = wet(s["id"], s)
        e = np.sum(y[0] ** 2)
        if ref is None:
            ref = e
        g = np.sqrt(ref / e * 10 ** (s["db"] / 10)) if e > 0 else 0.0
        comp[s["id"]] = y * g
        if s.get("learnedTake"):                 # second robot-only take, same placement and level rule
            y2 = wet(s["learnedTake"], s)
            e2 = np.sum(y2[0] ** 2)
            take2[s["id"]] = y2 * (np.sqrt(ref / e2 * 10 ** (s["db"] / 10)) if e2 > 0 else 0.0)
    rng = np.random.default_rng(seed)
    room_noise = rng.standard_normal((M, n)) * np.sqrt(ref / n / 10 ** (geo["roomDb"] / 10))
    mix = sum(comp.values()) + room_noise
    X = to_stft(mix, fs)
    Xtake = to_stft(sum(take2.values()) + room_noise[:, ::-1], fs) if take2 else None

    scores, audio = {}, {"mic1": mix[0]}
    for s in srcs:
        if s["kind"] != "speaker" or not s["target"]:
            continue
        sid, yT = s["id"], comp[s["id"]]
        XT, XR = to_stft(yT, fs), to_stft(mix - yT, fs)
        scores[f"mic_{sid}"] = db(XT[0], XR[0])
        d = steering(rel, s["az"], s["el"], fs)
        beams = {"das": d / M, "mvdr": mvdr(X, d)}
        if Xtake is not None:
            beams["learned"] = mvdr(np.concatenate([X, 3 * Xtake], axis=2), d)
        for k, w in beams.items():
            scores[f"{sid}_{k}"] = db(apply(w, XT), apply(w, XR))
            if wav_dir:
                audio[f"{sid}_{k}"] = to_time(apply(w, X), fs, n)
    if wav_dir:
        os.makedirs(wav_dir, exist_ok=True)
        scale = 0.9 / np.max(np.abs(mix))       # one gain for every file, as sim_conversation.py did
        for k, x in audio.items():
            sf.write(os.path.join(wav_dir, k + ".wav"), np.clip(x * scale, -1, 1), fs, subtype="PCM_16")
    info = {"pyroomacoustics": pra.__version__, "max_order": int(order), "rir_seconds": round(t_rir, 1),
            "total_seconds": round(time.time() - t0, 1), "room_noise_seed": seed}
    return scores, info


LABEL = {"mic": "mic 1 alone", "das": "delay-and-sum", "mvdr": "MVDR", "learned": "MVDR + learned robot noise"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene", help="the page's zip, or a folder from web/tools/export_scene.js")
    ap.add_argument("--json", help="also write the Python scores here")
    ap.add_argument("--wav-dir", help="also write the Python audio here (mic1.wav, <speaker>_<beam>.wav)")
    a = ap.parse_args(argv)
    sc = Scene(a.scene)
    name = sc.geo.get("name") or os.path.basename(a.scene)
    print(f"{name}: room {sc.geo['room']} m, RT60 {sc.geo['rt60']} s, damping {sc.geo['damping']}, "
          f"{len(sc.geo['mics'])} mics, {len(sc.geo['sources'])} sources")
    scores, info = score(sc, wav_dir=a.wav_dir)
    print(f"  pyroomacoustics {info['pyroomacoustics']}, image-source order {info['max_order']}, "
          f"room {info['rir_seconds']} s, total {info['total_seconds']} s\n")
    print(f"  {'score (target vs everything else)':42s} {'Python':>8s} {'page':>8s} {'diff':>7s}")
    for k, v in scores.items():
        who, kind = (k[4:], "mic") if k.startswith("mic_") else k.split("_", 1)
        p = sc.page.get(k) if sc.page else None
        print(f"  {who + ', ' + LABEL[kind]:42s} {v:8.1f} "
              + (f"{p:8.1f} {p - v:+7.1f}" if p is not None else f"{'-':>8s}"))
    if a.json:
        json.dump({"scene": name, "scores": scores, "info": info}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
