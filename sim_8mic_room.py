"""
sim_8mic_room.py  -  the simulated 8-mic room, used by every experiment.

You normally don't edit or run this file directly. Each experiment in the
experiments/ folder calls it with its own settings and saves into its own
folder under results/, so nothing is ever overwritten:

  python experiments/exp01_echo_levels.py
  python experiments/exp02_array_size.py
  ...

What one scene does
  1. Builds a reverberant room with an 8-mic circular array (robot-head sized),
     one or two talkers and background noise. Saves the 8-channel mix.
  2. Finds the talkers' directions with MUSIC and SRP-PHAT.
  3. Beamforms toward talker A: delay-and-sum, then MVDR (MPDR form).
  4. Removes echo with WPE, then beamforms again.
  5. Saves talker A's clean voice, dry and as heard at mic 1, for scoring later.

Running this file directly reproduces the original three echo levels
(results/exp01_echo_levels) - kept so check_setup.py still works.

Install once: pip install pyroomacoustics nara_wpe soundfile matplotlib scipy numpy
"""
import csv
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from nara_wpe.wpe import wpe
from scipy.signal import istft, resample_poly, stft

ROOT = os.path.dirname(os.path.abspath(__file__))    # the robot-audio folder
RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "speech_cache")

FS = 16000
N_MICS = 8
NFFT, HOP = 512, 128          # same framing as the implementation note
C = 343.0

# Default scene. Experiments override only what they test.
DEFAULTS = dict(
    rt60=0.5,          # echo time (s): 0.2 dry office ... 0.8 echoey hall
    radius=0.05,       # array radius (m); 0.05 = 10 cm across, robot-head sized
    snr_db=15,         # background noise, dB below the talkers
    angle_a=40,        # talker A direction (deg); the one we focus on
    angle_b=150,       # talker B direction (deg); None = only talker A
    dist=1.5,          # talker distance from the array (m)
    room=(6.0, 5.0, 3.0),
    doa_band=(300, 3500),  # frequency range (Hz) the direction finders look at
)

BASE = "https://raw.githubusercontent.com/LCAV/pyroomacoustics/master/examples/input_samples/"
SPEECH = ["cmu_arctic_us_aew_a0001.wav", "cmu_arctic_us_axb_a0004.wav"]


# ---------------------------------------------------------------- helpers
def load_speech(name):
    """Download a short public-domain speech clip once; return it at FS."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        urllib.request.urlretrieve(BASE + name, path)
    x, fs = sf.read(path)
    x = x[:, 0] if x.ndim > 1 else x
    if fs != FS:
        x = resample_poly(x, FS, fs)
    return x / np.max(np.abs(x))


def simulate(sources, centre, mic_xy, rt60, room):
    """Simulate sources in the room; returns (mics, samples)."""
    e_abs, max_order = pra.inverse_sabine(rt60, room)
    r = pra.ShoeBox(list(room), fs=FS, materials=pra.Material(e_abs), max_order=max_order)
    for pos, sig in sources:
        r.add_source(pos, signal=sig)
    r.add_microphone_array(pra.MicrophoneArray(np.vstack([mic_xy, np.full(N_MICS, centre[2])]), FS))
    r.simulate()
    return r.mic_array.signals


def to_stft(x):
    return stft(x, fs=FS, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[2]


def to_time(X):
    return istft(X, fs=FS, window="hann", nperseg=NFFT, noverlap=NFFT - HOP)[1]


def steering(rel_xy, angle_deg):
    """Far-field steering vectors, shape (freqs, mics)."""
    f = np.arange(NFFT // 2 + 1) * FS / NFFT
    u = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    return np.exp(2j * np.pi * f[:, None] * (rel_xy.T @ u)[None, :] / C)


def mpdr_weights(X, d, load=1e-3):
    """MVDR using the mixture covariance (needs no knowledge of the noise)."""
    F, M = d.shape
    w = np.zeros((F, M), dtype=complex)
    for f in range(F):
        R = X[:, f, :] @ X[:, f, :].conj().T / X.shape[2]
        R += load * np.trace(R).real / M * np.eye(M)
        Rd = np.linalg.solve(R, d[f])
        w[f] = Rd / (d[f].conj() @ Rd)
    return w


def apply(w, X):
    return np.einsum("fm,mft->ft", w.conj(), X)


def power(x):
    return np.mean(np.abs(x) ** 2)


def ratio_db(target, rest):
    return 10 * np.log10(power(target) / power(rest))


# ---------------------------------------------------------------- one scene
def run_scene(out, **settings):
    """Simulate and process one scene; save everything into `out`; return the scores."""
    cfg = {**DEFAULTS, **settings}
    os.makedirs(out, exist_ok=True)
    room = cfg["room"]
    centre = np.array([room[0] / 2, room[1] / 2, 1.5])
    mic_xy = pra.circular_2D_array(centre[:2], N_MICS, 0, cfg["radius"])
    rel_xy = mic_xy - centre[:2, None]
    two = cfg["angle_b"] is not None

    sA, sB = load_speech(SPEECH[0]), load_speech(SPEECH[1])
    n = max(len(sA), len(sB))
    sA, sB = np.pad(sA, (0, n - len(sA))), np.pad(sB, (0, n - len(sB)))

    def pos(angle):
        a = np.radians(angle)
        return centre + cfg["dist"] * np.array([np.cos(a), np.sin(a), 0.0])

    # Each talker is simulated separately so the result can be scored exactly.
    yA = simulate([(pos(cfg["angle_a"]), sA)], centre, mic_xy, cfg["rt60"], room)
    yB = simulate([(pos(cfg["angle_b"]), sB)], centre, mic_xy, cfg["rt60"], room) if two else np.zeros_like(yA)
    L = min(yA.shape[1], yB.shape[1])
    yA, yB = yA[:, :L], yB[:, :L]
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(yA.shape)
    noise *= np.sqrt(power(yA[0] + yB[0]) / power(noise[0]) / 10 ** (cfg["snr_db"] / 10))
    interf = yB + noise
    mix = yA + interf

    scale = 0.9 / np.max(np.abs(mix))
    sf.write(os.path.join(out, "mix_8ch.wav"), (mix * scale).T, FS)
    sf.write(os.path.join(out, "1_mic0_input.wav"), mix[0] * scale, FS)
    sf.write(os.path.join(out, "clean_A_dry.wav"), 0.9 * sA, FS)                  # what A said
    sf.write(os.path.join(out, "clean_A_at_mic1.wav"), yA[0] * scale, FS)         # A + room, no B, no noise
    np.savetxt(os.path.join(out, "mic_positions_m.txt"), np.vstack([rel_xy, np.zeros(N_MICS)]).T,
               fmt="%.5f", header="x y z (metres, relative to array centre)")

    X, XA, XI = to_stft(mix), to_stft(yA), to_stft(interf)
    res = {}

    # ---- direction finding
    grid = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    for name in ["MUSIC", "SRP"]:
        doa = pra.doa.algorithms[name](rel_xy, FS, NFFT, c=C, num_src=2 if two else 1, azimuth=grid)
        doa.locate_sources(X, freq_range=list(cfg["doa_band"]))
        res[name] = " ".join(f"{a:.0f}" for a in np.sort(np.degrees(doa.azimuth_recon)))
        g = np.real(doa.grid.values)
        ax.plot(np.degrees(grid), (g - g.min()) / (np.ptp(g) + 1e-12), label=name)
    for a in ([cfg["angle_a"], cfg["angle_b"]] if two else [cfg["angle_a"]]):
        ax.axvline(a, color="k", ls="--", lw=0.8)
    ax.set(xlabel="direction (deg)", ylabel="normalised score", title="Where is sound coming from?")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "doa_spectrum.png"), dpi=120)
    plt.close(fig)

    # ---- beamforming toward A
    d = steering(rel_xy, cfg["angle_a"])
    res["mic"] = ratio_db(XA[0], XI[0])
    w = d / N_MICS
    res["das"] = ratio_db(apply(w, XA), apply(w, XI))
    sf.write(os.path.join(out, "2_delay_and_sum_A.wav"), to_time(apply(w, X)) * scale, FS)
    w = mpdr_weights(X, d)
    res["mvdr"] = ratio_db(apply(w, XA), apply(w, XI))
    sf.write(os.path.join(out, "3_mvdr_A.wav"), to_time(apply(w, X)) * scale, FS)

    # ---- echo removal (offline WPE), then beamform
    Xd = wpe(X.transpose(1, 0, 2), taps=10, delay=3, iterations=3).transpose(1, 0, 2)
    sf.write(os.path.join(out, "4_wpe_mic0.wav"), to_time(Xd[0]) * scale, FS)
    w = mpdr_weights(Xd, d)
    sf.write(os.path.join(out, "5_wpe_then_mvdr_A.wav"), to_time(apply(w, Xd)) * scale, FS)
    return res


# ---------------------------------------------------------------- one experiment
def run_experiment(name, question, runs):
    """
    name:     folder name under results/, e.g. "exp01_echo_levels"
    question: one line saying what the experiment is about
    runs:     list of (label, {settings}) - one scene per entry
    Saves each scene in results/<name>/<label>/ and the table in summary.txt / summary.csv.
    """
    folder = os.path.join(RESULTS, name)
    os.makedirs(folder, exist_ok=True)
    print(f"\n{name}: {question}")
    rows = []
    for label, settings in runs:
        cfg = {**DEFAULTS, **settings}
        print(f"  running {label} ...", flush=True)
        r = run_scene(os.path.join(folder, label), **settings)
        truth = f"{cfg['angle_a']}" + (f" {cfg['angle_b']}" if cfg["angle_b"] is not None else "")
        band = f"{cfg['doa_band'][0]}-{cfg['doa_band'][1]}"
        rows.append([label, cfg["rt60"], round(cfg["radius"] * 100, 1), cfg["snr_db"], band, truth,
                     r["MUSIC"], r["SRP"], round(r["mic"], 1), round(r["das"], 1), round(r["mvdr"], 1)])

    head = ["scene", "RT60 s", "radius cm", "SNR dB", "DOA band Hz", "true deg", "MUSIC deg", "SRP deg",
            "mic dB", "DAS dB", "MVDR dB"]
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    line = lambda r: " | ".join(str(x).rjust(w) for x, w in zip(r, widths))
    table = "\n".join([line(head), "-+-".join("-" * w for w in widths)] + [line(r) for r in rows])
    text = (f"{name}\n{question}\n\n{table}\n\n"
            "dB columns: talker A vs everything else (higher = cleaner). "
            "DAS = delay-and-sum, MVDR = MVDR beamformer.\n")
    with open(os.path.join(folder, "summary.txt"), "w") as f:
        f.write(text)
    with open(os.path.join(folder, "summary.csv"), "w", newline="") as f:
        csv.writer(f).writerows([head] + rows)
    print("\n" + table)
    print(f"\nSaved in {folder}  (summary.txt has this table)")


if __name__ == "__main__":
    run_experiment("exp01_echo_levels", "What does room echo do to speech and to the processing?",
                   [("rt02_dry", dict(rt60=0.2)), ("rt05_medium", dict(rt60=0.5)), ("rt08_echoey", dict(rt60=0.8))])
