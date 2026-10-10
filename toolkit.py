"""
toolkit.py - building blocks for experiments 07 and later.

Experiments 01-06 use sim_8mic_room.run_experiment (one fixed processing chain).
Later experiments need to change one processing step at a time, so they use
these smaller pieces instead. Everything here reuses the same room, speech,
array and framing as sim_8mic_room.py, so results stay comparable.
"""
import csv
import os
import time
from types import SimpleNamespace

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy.signal import fftconvolve

import sim_8mic_room as room

FS, N_MICS, NFFT, HOP, C = room.FS, room.N_MICS, room.NFFT, room.HOP, room.C
RESULTS = room.RESULTS
to_stft, to_time, steering, apply, power, ratio_db = (
    room.to_stft, room.to_time, room.steering, room.apply, room.power, room.ratio_db)
mpdr_weights = room.mpdr_weights

# Fixed scenes from experiment 5, so later phases are measured on the same audio.
TEST_SET = [
    ("one_talker", dict(angle_b=None)),
    ("two_far", dict(angle_b=150)),
    ("two_close", dict(angle_b=70)),
    ("dry_room", dict(rt60=0.2)),
    ("echoey_room", dict(rt60=0.8)),
]


# ---------------------------------------------------------------- scenes
def build_scene(b_start=0.0, **settings):
    """Simulate a scene and keep every component separately.
    b_start: seconds of silence before talker B starts (0 = both start together,
    which reproduces experiments 01-06 exactly)."""
    cfg = {**room.DEFAULTS, **settings}
    rm = cfg["room"]
    centre = np.array([rm[0] / 2, rm[1] / 2, 1.5])
    mic_xy = pra.circular_2D_array(centre[:2], N_MICS, 0, cfg["radius"])
    rel_xy = mic_xy - centre[:2, None]
    two = cfg["angle_b"] is not None

    sA, sB = room.load_speech(room.SPEECH[0]), room.load_speech(room.SPEECH[1])
    if b_start > 0:
        sB = np.concatenate([np.zeros(int(b_start * FS)), sB])
    n = max(len(sA), len(sB))
    sA, sB = np.pad(sA, (0, n - len(sA))), np.pad(sB, (0, n - len(sB)))

    def pos(angle):
        a = np.radians(angle)
        return centre + cfg["dist"] * np.array([np.cos(a), np.sin(a), 0.0])

    yA = room.simulate([(pos(cfg["angle_a"]), sA)], centre, mic_xy, cfg["rt60"], rm)
    yB = room.simulate([(pos(cfg["angle_b"]), sB)], centre, mic_xy, cfg["rt60"], rm) if two else np.zeros_like(yA)
    L = min(yA.shape[1], yB.shape[1])
    yA, yB = yA[:, :L], yB[:, :L]
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(yA.shape)
    noise *= np.sqrt(power(yA[0] + yB[0]) / power(noise[0]) / 10 ** (cfg["snr_db"] / 10))
    interf = yB + noise
    mix = yA + interf
    return SimpleNamespace(cfg=cfg, centre=centre, mic_xy=mic_xy, rel_xy=rel_xy, two=two,
                           sA=sA, sB=sB, yA=yA, yB=yB, noise=noise, interf=interf, mix=mix,
                           scale=0.9 / np.max(np.abs(mix)),
                           X=to_stft(mix), XA=to_stft(yA), XB=to_stft(yB), XI=to_stft(interf))


# ---------------------------------------------------------------- direction finding
def find_directions(X, rel_xy, method="SRP", num_src=2, band=(300, 3500)):
    """Returns (sorted angles in degrees, score per degree 0..359)."""
    grid = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    doa = pra.doa.algorithms[method](rel_xy, FS, NFFT, c=C, num_src=num_src, azimuth=grid)
    doa.locate_sources(X, freq_range=list(band))
    return np.sort(np.degrees(doa.azimuth_recon)), np.real(doa.grid.values)


def angle_error(est, true):
    """Smallest difference between two angles, in degrees."""
    return abs((est - true + 180) % 360 - 180)


def fmt_angles(a):
    return " ".join(f"{x:.0f}" for x in a)


# ---------------------------------------------------------------- beamforming
def component_db(w, XA, XI):
    """Talker A vs everything else after the beamformer w (same as the earlier tables)."""
    return ratio_db(apply(w, XA), apply(w, XI))


def blockwise_mpdr(X, d, block_frames):
    """MVDR (MPDR form) re-estimated on each block of frames, like a live system.
    Returns weights per frame, shape (frames, freqs, mics)."""
    T = X.shape[2]
    W = np.zeros((T, d.shape[0], d.shape[1]), dtype=complex)
    for s in range(0, T, block_frames):
        e = min(T, s + block_frames)
        W[s:e] = mpdr_weights(X[:, :, s:e], d)[None]
    return W


def apply_framewise(W, X):
    return np.einsum("tfm,mft->ft", W.conj(), X)


def mask_mvdr_weights(X, mask, ref=0, load=1e-3):
    """Mask-based MVDR (Souden form). mask: (freqs, frames) in [0,1], 1 = target.
    Target and noise covariances are weighted by the mask; no direction needed."""
    F, M = X.shape[1], X.shape[0]
    w = np.zeros((F, M), dtype=complex)
    for f in range(F):
        Xf = X[:, f, :]
        m = mask[f]
        Rs = (Xf * m) @ Xf.conj().T / (m.sum() + 1e-9)
        Rn = (Xf * (1 - m)) @ Xf.conj().T / ((1 - m).sum() + 1e-9)
        Rn += load * np.trace(Rn).real / M * np.eye(M) + 1e-12 * np.eye(M)
        num = np.linalg.solve(Rn, Rs)
        w[f] = num[:, ref] / (np.trace(num) + 1e-12)
    return w


# ---------------------------------------------------------------- echo removal
def wpe_offline(X, taps=10, delay=3, iterations=3):
    from nara_wpe.wpe import wpe
    return wpe(X.transpose(1, 0, 2), taps=taps, delay=delay, iterations=iterations).transpose(1, 0, 2)


def wpe_online(X, taps=10, delay=3, alpha=0.99):
    """Frame-by-frame WPE, like the robot would run it (nara_wpe OnlineWPE)."""
    from nara_wpe.wpe import OnlineWPE
    M, F, T = X.shape
    Y = X.transpose(2, 1, 0)                      # (frames, freqs, mics)
    out = np.zeros_like(Y)
    online = OnlineWPE(taps=taps, delay=delay, alpha=alpha, channel=M, frequency_bins=F)
    for t in range(T):
        out[t] = online.step_frame(Y[t])
    return out.transpose(2, 1, 0)


# ---------------------------------------------------------------- scoring
def si_sdr(est, ref, max_lag=0.25):
    """Scale-invariant SDR (dB) of est against ref, after finding the best time alignment.
    Penalises everything that isn't the clean target: other talkers, noise AND echo."""
    est, ref = np.asarray(est, float), np.asarray(ref, float)
    n = min(len(est), len(ref))
    xc = fftconvolve(est[:n], ref[:n][::-1], mode="full")
    mid, lag_max = n - 1, int(max_lag * FS)
    lag = np.argmax(np.abs(xc[mid - lag_max: mid + lag_max + 1])) - lag_max
    if lag > 0:
        e, r = est[lag:n], ref[: n - lag]
    else:
        e, r = est[: n + lag], ref[-lag:n]
    alpha = np.dot(e, r) / (np.dot(r, r) + 1e-12)
    target = alpha * r
    return 10 * np.log10(np.sum(target ** 2) / (np.sum((e - target) ** 2) + 1e-12))


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.s = time.perf_counter() - self.t


# ---------------------------------------------------------------- saving
def result_dir(name, *sub):
    d = os.path.join(RESULTS, name, *sub)
    os.makedirs(d, exist_ok=True)
    return d


def save_wav(path, x, scale=None):
    x = np.asarray(x, float)
    s = scale if scale is not None else 0.9 / (np.max(np.abs(x)) + 1e-12)
    sf.write(path, np.clip(x * s, -1, 1), FS)


def save_table(name, question, head, rows, notes=""):
    folder = result_dir(name)
    rows = [[(round(x, 1) if isinstance(x, float) else x) for x in r] for r in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    line = lambda r: " | ".join(str(x).rjust(w) for x, w in zip(r, widths))
    table = "\n".join([line(head), "-+-".join("-" * w for w in widths)] + [line(r) for r in rows])
    with open(os.path.join(folder, "summary.txt"), "w") as f:
        f.write(f"{name}\n{question}\n\n{table}\n\n{notes}\n")
    with open(os.path.join(folder, "summary.csv"), "w", newline="") as f:
        csv.writer(f).writerows([head] + rows)
    print(f"\n{name}: {question}\n\n{table}\n")
    if notes:
        print(notes)
    print(f"\nSaved in {folder}  (summary.txt has this table)")
